"""
api/index.py — Backend BioAI-Pulse (Vercel serverless / Flask WSGI)

Trasy:
  POST /api/login            — logowanie PIN-em
  GET  /api/data?goal=...    — pełny pakiet analiz (z wybranym celem)
  GET  /api/report           — narracyjny raport (Groq jeśli jest, inaczej z analytics)
  POST /api/chat             — czat z AI-coachem; potrafi ustawić cel aplikacji
  GET  /api/export           — surowe dane
  GET  /api/push/key         — publiczny klucz VAPID do subskrypcji push
  POST /api/push/subscribe   — zapis subskrypcji powiadomień
  POST /api/push/test        — wyślij testowe powiadomienie na telefon
  GET/POST /api/reminders    — odczyt / zapis ustawień przypominajek
  GET  /api/cron/reminders   — (wołane przez cron VPS) wysyła zaległe przypominajki

Lokalnie: python3 api/index.py  → http://127.0.0.1:8000  (serwuje też public/)
Na Vercel: public/ serwowane statycznie, tu trafia tylko /api/*.
"""

from __future__ import annotations

import os
import re
import sys
import json
import hmac
import time
import base64
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import analytics  # noqa: E402

load_dotenv(ROOT / ".env", override=True)

# ---------------------------------------------------------------------------
# Konfiguracja
# ---------------------------------------------------------------------------

PUBLIC_DIR    = ROOT / "public"
REAL_METRICS  = ROOT / "data" / "daily_metrics.json"
DEMO_METRICS  = ROOT / "data" / "demo_metrics.json"
REPORTS_DIR   = ROOT / "data" / "reports"

APP_PIN       = os.getenv("APP_PIN", "2137")
SECRET        = os.getenv("APP_SECRET", "bioaipulse-zmien-mnie").encode()
TOKEN_TTL     = 60 * 60 * 24 * 30
TZ            = timezone(timedelta(hours=2))  # CEST

app = Flask(__name__, static_folder=None)

# ---------------------------------------------------------------------------
# Storage: Vercel KV (Upstash REST) jeśli dostępne, inaczej lokalny plik
# ---------------------------------------------------------------------------

KV_URL   = os.getenv("KV_REST_API_URL")
KV_TOKEN = os.getenv("KV_REST_API_TOKEN")
LOCAL_STORE = ROOT / "data" / "store.json"


def _local_read() -> dict:
    if LOCAL_STORE.exists():
        try:
            return json.loads(LOCAL_STORE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _local_write(d: dict):
    LOCAL_STORE.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def store_get(key: str, default=None):
    if KV_URL and KV_TOKEN:
        import requests
        r = requests.get(f"{KV_URL}/get/{key}", headers={"Authorization": f"Bearer {KV_TOKEN}"}, timeout=8)
        if r.ok:
            val = r.json().get("result")
            return json.loads(val) if val else default
        return default
    return _local_read().get(key, default)


def store_set(key: str, value):
    if KV_URL and KV_TOKEN:
        import requests
        requests.post(f"{KV_URL}/set/{key}", headers={"Authorization": f"Bearer {KV_TOKEN}"},
                      data=json.dumps(value), timeout=8)
        return
    d = _local_read()
    d[key] = value
    _local_write(d)


# ---------------------------------------------------------------------------
# Dane
# ---------------------------------------------------------------------------

def _has_real_data() -> bool:
    if not REAL_METRICS.exists():
        return False
    try:
        data = json.loads(REAL_METRICS.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = [data]
        return any(e.get("steps") or _sleep_min(e) or e.get("hrv_rmssd") for e in data)
    except (json.JSONDecodeError, OSError):
        return False


def _sleep_min(e):
    return (e.get("sleep") or {}).get("total_minutes")


def load_history():
    force_demo = os.getenv("DEMO_MODE", "").strip() in ("1", "true", "yes")
    use_real = (not force_demo) and _has_real_data()
    path = REAL_METRICS if use_real else DEMO_METRICS
    if not path.exists():
        return [], (not use_real)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [data]
    return data, (not use_real)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def make_token() -> str:
    exp = str(int(time.time()) + TOKEN_TTL)
    sig = hmac.new(SECRET, exp.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{exp}.{sig}".encode()).decode()


def valid_token(token: str) -> bool:
    try:
        exp, sig = base64.urlsafe_b64decode(token.encode()).decode().split(".", 1)
        expected = hmac.new(SECRET, exp.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected) and int(exp) > time.time()
    except (ValueError, TypeError):
        return False


def require_auth() -> bool:
    auth = request.headers.get("Authorization", "")
    return auth.startswith("Bearer ") and valid_token(auth[7:])


# ---------------------------------------------------------------------------
# Raport narracyjny
# ---------------------------------------------------------------------------

def latest_groq_report():
    if not REPORTS_DIR.exists():
        return None
    files = sorted(REPORTS_DIR.glob("*.txt"))
    return files[-1].read_text(encoding="utf-8") if files else None


def build_narrative(bundle) -> str:
    r = bundle["readiness"]
    lines = ["RAPORT GOTOWOŚCI", "━" * 24]
    if r.get("score") is not None:
        lines.append(f"DAILY READINESS: {r['score']}/100 — {r['label']}")
    lines += ["", r.get("summary", ""), ""]
    for f in bundle.get("readiness_factors", []):
        mark = {"good": "✓", "ok": "•", "bad": "✗"}[f["status"]]
        lines.append(f"{mark} {f['name']}: {f['note']}")
    cons = bundle.get("consistency")
    if cons:
        lines += ["", f"Regularność snu: {cons['label']} (śr. {cons['avg_bedtime']})."]
    if bundle.get("insights"):
        lines += ["", "NA CO UWAŻAĆ:"]
        for i in bundle["insights"]:
            lines.append(f"{i['icon']} {i['title']} — {i['text']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trasy: dane
# ---------------------------------------------------------------------------

@app.post("/api/login")
def login():
    pin = str((request.get_json(silent=True) or {}).get("pin", ""))
    if hmac.compare_digest(pin, APP_PIN):
        return jsonify({"ok": True, "token": make_token()})
    return jsonify({"ok": False, "error": "Błędny PIN"}), 401


@app.get("/api/data")
def api_data():
    if not require_auth():
        return jsonify({"error": "unauthorized"}), 401
    goal = request.args.get("goal", "maintain")
    history, is_demo = load_history()
    if not history:
        return jsonify({"empty": True, "is_demo": is_demo})

    # Pobierz zapisane dynamiczne cele i wstrzyknij do analytics
    custom_goals = store_get("custom_goals", {})
    bundle = analytics.analyze(history, goal=goal, custom_goals=custom_goals)
    bundle["is_demo"] = is_demo
    return jsonify(bundle)


@app.get("/api/report")
def api_report():
    if not require_auth():
        return jsonify({"error": "unauthorized"}), 401
    history, is_demo = load_history()
    groq = latest_groq_report()
    if groq and not is_demo:
        return jsonify({"source": "groq", "text": groq})
    if not history:
        return jsonify({"source": "none", "text": "Brak danych."})
    return jsonify({"source": "generated", "text": build_narrative(analytics.analyze(history))})


@app.get("/api/export")
def api_export():
    if not require_auth():
        return jsonify({"error": "unauthorized"}), 401
    history, _ = load_history()
    return jsonify(history)


# ---------------------------------------------------------------------------
# Czat z AI-coachem (Groq) — potrafi ustawić cel aplikacji
# ---------------------------------------------------------------------------

CHAT_SYSTEM = """Jesteś Pulse — osobisty coach zdrowia Franka. Mówisz po polsku. Jesteś zwięzły: max 3-4 zdania na odpowiedź. Bez wstępów, bez powtarzania pytania użytkownika, bez motywacyjnego lania wody. Konkrety.

Odpowiadasz na KAŻDE pytanie: trening, sen, dane z opaski, odżywianie, motywacja. Zawsze używaj konkretnych liczb z danych użytkownika.

TWOJA NAJWAŻNIEJSZA UMIEJĘTNOŚĆ — TWORZENIE DOWOLNEGO CELU:
Użytkownik może powiedzieć COKOLWIEK: bieganie, pływanie, skakanka, karate, wspinaczka, taniec, joga, spacery z psem — dosłownie cokolwiek. Twoim zadaniem jest stworzyć dla tej aktywności spersonalizowany cel.

ZASADA (3 kroki):
1. Dopytaj o 1-2 szczegóły (jak często? jak długo? jaki poziom?).
2. Gdy masz dość info — potwierdź naturalnie i dołącz na SAMYM KOŃCU blok (użytkownik go nie widzi):

<<SET_GOAL:JSON>>

gdzie JSON to obiekt (bez spacji po <<SET_GOAL:):
{
  "goal": "unikalny_id_bez_spacji",
  "label": "Ładna nazwa po polsku",
  "emoji": "🎯",
  "plan_hard": ["zadanie gdy gotowość wysoka","drugie","trzecie"],
  "plan_mid": ["zadanie gdy gotowość średnia","drugie"],
  "plan_easy": ["zadanie gdy gotowość niska / regeneracja","drugie"],
  "plan_headline_hard": "Krótki nagłówek planu",
  "plan_headline_mid": "Krótki nagłówek",
  "plan_headline_easy": "Odpoczynek / regeneracja",
  "daily_task": "Główne zadanie dnia (jedno zdanie)",
  "note": "szczegóły które podał użytkownik"
}

PRZYKŁADY poprawnych bloków:
<<SET_GOAL:{"goal":"rope_jumping","label":"Skakanka","emoji":"🪢","plan_hard":["5 serii 2 min skakania / 1 min przerwy","Ćwicz podwójne obroty","Rozciągnij łydki po"],"plan_mid":["3×1 min skakania / 1 min przerwy","Skup się na technice","Lekkie rozgrzanie przed"],"plan_easy":["10 min lekkiego skakania","Praca nad rytmem","Odpuść intensywność"],"plan_headline_hard":"Skakanka — interwały","plan_headline_mid":"Skakanka — umiarkowanie","plan_headline_easy":"Lekko i technicznie","daily_task":"Skakanka: 5×2 min interwałów (codziennie 20 min)","note":"codziennie 20 minut"}>>

<<SET_GOAL:{"goal":"karate","label":"Karate","emoji":"🥋","plan_hard":["45 min trening kumite","Kata 3 razy z pełną intensywnością","Ćwiczenia siłowe kończyn"],"plan_mid":["30 min kata i techniki","Spokojne kumite z partnerem","Stretching po"],"plan_easy":["Kata 1 raz powoli","Stretching 15 min","Ćwiczenia oddechu"],"plan_headline_hard":"Karate — pełny trening","plan_headline_mid":"Karate — techniki","plan_headline_easy":"Regeneracja i kata","daily_task":"Karate: kata + 20 min kumite","note":"3x w tygodniu"}>>

ZASADY:
- id: małe litery, podkreślniki (rope_jumping, karate, joga_poranna, taniec_latino)
- emoji: ZAWSZE dobierz odpowiednie (🪢🥋🧗🕺🧘🤸🏇⛷️🎾🏌️🎯 itd.)
- plan_hard/mid/easy: minimum 2-3 konkretne zadania, dostosowane do tej aktywności
- daily_task: jedno zdanie, konkretne (to pojawi się w checkliście na głównym ekranie)
- KRYTYCZNE: Gdy potwierdzasz zmianę — blok <<SET_GOAL:...>> jest OBOWIĄZKOWY. Bez niego aplikacja nie zmieni celu i ekran główny nie zostanie zaktualizowany. Użytkownik będzie sfrustrowany.
- Nie wstawiaj bloku przy zwykłej rozmowie — tylko przy finalnym potwierdzeniu.

Nie diagnozujesz chorób."""

GOAL_KEYWORDS = {
    "swimming":   ["pływa", "pływanie", "basen", "kraul", "swim"],
    "running":    ["biega", "bieg", "bieganie"],
    "cycling":    ["rower", "kolarz", "jazda"],
    "strength":   ["siłow", "siła", "mięśni", "masę", "kulturyst"],
    "weight_loss":["schud", "wagi", "tłuszcz", "redukc", "odchud"],
    "sleep":      ["sen ", "spać", "wysyp", "zasypia"],
    "maintain":   ["utrzyma", "formę"],
}


def _detect_goal(text):
    low = text.lower()
    for gid, kws in GOAL_KEYWORDS.items():
        if any(k in low for k in kws):
            return gid
    return None


@app.post("/api/chat")
def api_chat():
    if not require_auth():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    messages = body.get("messages", [])
    goal = body.get("goal", "maintain")
    history, _ = load_history()
    bundle = analytics.analyze(history, goal=goal) if history else {}
    today = bundle.get("today", {})
    ready = bundle.get("readiness", {})
    sleep = today.get("sleep") or {}
    base = bundle.get("baselines", {})

    def _avg(getter, n=7):
        vals = [getter(e) for e in history[-n:] if getter(e) is not None]
        return round(sum(vals)/len(vals), 1) if vals else None

    goal_label = analytics.GOALS.get(goal, {}).get("label", goal)
    ins = "; ".join(i["title"] for i in bundle.get("insights", [])) or "brak"
    ctx = (
        "[Aktualne dane Franka z opaski]\n"
        f"Aktywny cel aplikacji: {goal_label}\n"
        f"Daily Readiness: {ready.get('score')}/100 ({ready.get('label')})\n"
        f"Sleep Score: {sleep.get('sleep_score')}/100, sen {round((sleep.get('total_minutes') or 0)/60,1)}h\n"
        f"Tętno spocz.: {today.get('resting_hr_bpm')} bpm (norma {base.get('rhr')}), "
        f"HRV: {today.get('hrv_rmssd')} ms (norma {base.get('hrv')})\n"
        f"SpO2: {today.get('spo2_pct')}%, oddech: {today.get('respiration_rate')}/min, "
        f"temp. skóry: {today.get('skin_temp_variation_c')}°C, obciążenie kardio: {today.get('cardio_load')}\n"
        f"Kroki: {today.get('steps')}, dystans: {today.get('distance_km')} km, "
        f"minuty strefy: {today.get('active_zone_minutes')}, kalorie: {today.get('calories_kcal')}\n"
        f"Średnie 7 dni: sen {_avg(lambda e:(e.get('sleep') or {}).get('total_minutes'))} min, "
        f"kroki {_avg(lambda e:e.get('steps'))}, HRV {_avg(lambda e:e.get('hrv_rmssd'))}\n"
        f"Sygnały: {ins}"
    )

    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            msgs = [{"role": "system", "content": CHAT_SYSTEM}]
            for i, m in enumerate(messages):
                content = m["content"]
                if m["role"] == "user" and i == len(messages) - 1:
                    content = f"{content}\n\n{ctx}"
                msgs.append({"role": m["role"], "content": content})
            resp = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=msgs, max_tokens=600)
            reply = resp.choices[0].message.content
        except Exception as e:  # noqa: BLE001
            return jsonify({"reply": f"(Błąd AI: {e}) Możesz ustawić cel ręcznie w Profilu.", "set_goal": None})
    else:
        # Fallback bez klucza Groq — prosta heurystyka (na produkcji ustaw GROQ_API_KEY)
        last = (messages[-1]["content"] if messages else "").lower()
        intent = any(w in last for w in ["chcę", "chce", "zacz", "skup", "cel", "przejść", "przejdz", "zmień", "zmien", "ustaw"])
        g = _detect_goal(last)
        if g and intent:
            reply = (f"Jasne — ustawiam cel: {analytics.GOALS[g]['label']}. Dopasuję plany i statystyki pod to. "
                     f"(Pełna rozmowa AI ruszy po dodaniu klucza Groq.) <<SET_GOAL:{{\"goal\":\"{g}\"}}>>")
        else:
            reply = ("Działam teraz w trybie uproszczonym (bez klucza AI). Mogę ustawić cel — napisz np. "
                     "'chcę zacząć biegać'. Po podłączeniu klucza Groq odpowiem swobodnie na każde pytanie o Twoje dane.")

    # Wyciągnij dyrektywę SET_GOAL
    set_goal = None
    m = re.search(r"<<SET_GOAL:(\{.*?\})>>", reply, re.S)
    if m:
        try:
            payload = json.loads(m.group(1))
            # Normalizuj id — usuń polskie znaki i skróć do pierwszego słowa rdzenia
            raw_id = payload.get("goal", "").strip().lower()
            raw_id = raw_id.replace(" ", "_").replace("-", "_")
            # Usuwanie duplikatów: jeśli istnieje cel o id będącym prefiksem lub zawierającym ten rdzeń
            custom_goals = store_get("custom_goals", {})
            g = raw_id
            # Sprawdź czy nie ma już podobnego celu (np. "skakanka" gdy nowe id to "skakanka_codziennie")
            for existing_id in list(custom_goals.keys()):
                base = existing_id.split("_")[0]
                if raw_id.startswith(base) or base == raw_id.split("_")[0]:
                    g = existing_id  # aktualizuj istniejący zamiast tworzyć nowy
                    break
            if g:
                custom_goals[g] = {
                    "goal": g,
                    "label": payload.get("label", g),
                    "emoji": payload.get("emoji", "🎯"),
                    "plan_hard": payload.get("plan_hard", []),
                    "plan_mid": payload.get("plan_mid", []),
                    "plan_easy": payload.get("plan_easy", []),
                    "plan_headline_hard": payload.get("plan_headline_hard", "Wysoka gotowość"),
                    "plan_headline_mid": payload.get("plan_headline_mid", "Umiarkowanie"),
                    "plan_headline_easy": payload.get("plan_headline_easy", "Regeneracja"),
                    "daily_task": payload.get("daily_task", ""),
                    "note": payload.get("note", ""),
                }
                store_set("custom_goals", custom_goals)
                set_goal = {"goal": g, "label": custom_goals[g]["label"],
                            "emoji": custom_goals[g]["emoji"], "note": payload.get("note", "")}
        except json.JSONDecodeError:
            pass
        reply = reply[:m.start()].strip()

    return jsonify({"reply": reply, "set_goal": set_goal})


# ---------------------------------------------------------------------------
# Powiadomienia push (Web Push / VAPID)
# ---------------------------------------------------------------------------

VAPID_PUBLIC  = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:zgnilyziemniak123@gmail.com")
CRON_SECRET   = os.getenv("CRON_SECRET", "zmien-mnie")

DEFAULT_REMINDERS = [
    {"id": "water", "label": "Pij wodę", "emoji": "💧", "enabled": True, "kind": "interval", "every_min": 120, "from": "08:00", "to": "21:00", "body": "Czas na szklankę wody 💧"},
    {"id": "move", "label": "Rozrusz się", "emoji": "🚶", "enabled": True, "kind": "interval", "every_min": 90, "from": "09:00", "to": "20:00", "body": "Wstań i rozrusz się na chwilę 🚶"},
    {"id": "bedtime", "label": "Pora snu", "emoji": "🌙", "enabled": True, "kind": "daily", "time": "22:30", "body": "Czas zwalniać — przygotuj się do snu 🌙"},
    {"id": "morning", "label": "Poranny raport", "emoji": "☀️", "enabled": True, "kind": "daily", "time": "07:15", "body": "Twój raport gotowości jest gotowy ☀️"},
]


def get_reminders():
    return store_get("reminders", DEFAULT_REMINDERS)


@app.get("/api/push/key")
def push_key():
    return jsonify({"key": VAPID_PUBLIC, "configured": bool(VAPID_PUBLIC and VAPID_PRIVATE)})


@app.post("/api/push/subscribe")
def push_subscribe():
    if not require_auth():
        return jsonify({"error": "unauthorized"}), 401
    sub = request.get_json(silent=True) or {}
    subs = store_get("subscriptions", [])
    if sub not in subs:
        subs.append(sub)
        store_set("subscriptions", subs)
    return jsonify({"ok": True, "count": len(subs)})


def _send_push(sub, title, body):
    from pywebpush import webpush
    webpush(
        subscription_info=sub,
        data=json.dumps({"title": title, "body": body}),
        vapid_private_key=VAPID_PRIVATE,
        vapid_claims={"sub": VAPID_SUBJECT},
        timeout=10,
    )


@app.post("/api/push/test")
def push_test():
    if not require_auth():
        return jsonify({"error": "unauthorized"}), 401
    if not (VAPID_PUBLIC and VAPID_PRIVATE):
        return jsonify({"ok": False, "error": "Push nie skonfigurowany (brak kluczy VAPID)."}), 400
    subs = store_get("subscriptions", [])
    sent = 0
    for s in subs:
        try:
            _send_push(s, "BioAI-Pulse", "Testowe powiadomienie działa! ✅")
            sent += 1
        except Exception:  # noqa: BLE001
            pass
    return jsonify({"ok": True, "sent": sent, "subscriptions": len(subs)})


@app.route("/api/reminders", methods=["GET", "POST"])
def api_reminders():
    if not require_auth():
        return jsonify({"error": "unauthorized"}), 401
    if request.method == "POST":
        items = (request.get_json(silent=True) or {}).get("items")
        if items is not None:
            store_set("reminders", items)
        return jsonify({"ok": True, "items": get_reminders()})
    return jsonify({"items": get_reminders()})


@app.get("/api/cron/reminders")
def cron_reminders():
    """Wołane przez cron VPS co kilka minut. Wysyła zaległe przypominajki."""
    if request.args.get("key") != CRON_SECRET:
        return jsonify({"error": "forbidden"}), 403
    now = datetime.now(TZ)
    hm_now = now.strftime("%H:%M")
    minutes_now = now.hour * 60 + now.minute
    items = get_reminders()
    subs = store_get("subscriptions", [])
    state = store_get("reminder_state", {})
    sent = 0

    for it in items:
        if not it.get("enabled"):
            continue
        due = False
        if it["kind"] == "daily":
            last = state.get(it["id"], "")
            if hm_now == it.get("time") and last != now.strftime("%Y-%m-%d %H:%M"):
                due = True
        elif it["kind"] == "interval":
            fr = it.get("from", "00:00"); to = it.get("to", "23:59")
            fr_m = int(fr[:2]) * 60 + int(fr[3:]); to_m = int(to[:2]) * 60 + int(to[3:])
            if fr_m <= minutes_now <= to_m:
                last_min = state.get(it["id"] + "_min")
                if last_min is None or minutes_now - last_min >= it.get("every_min", 120):
                    due = True
        if due:
            for s in subs:
                try:
                    _send_push(s, "BioAI-Pulse", it.get("body", it["label"]))
                    sent += 1
                except Exception:  # noqa: BLE001
                    pass
            if it["kind"] == "daily":
                state[it["id"]] = now.strftime("%Y-%m-%d %H:%M")
            else:
                state[it["id"] + "_min"] = minutes_now

    store_set("reminder_state", state)
    return jsonify({"ok": True, "sent": sent, "time": hm_now})


@app.route("/api/goals/check", methods=["GET", "POST"])
def goals_check():
    """Zaznaczone zadania na dziś (klucz = data YYYY-MM-DD)."""
    if not require_auth():
        return jsonify({"error": "unauthorized"}), 401
    today_key = f"goals_{datetime.now(TZ).strftime('%Y-%m-%d')}"
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        checked = data.get("checked", [])
        store_set(today_key, checked)
        return jsonify({"ok": True, "checked": checked})
    return jsonify({"checked": store_get(today_key, [])})


@app.get("/api/ping")
def ping():
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Serwowanie public/ — tylko lokalnie (na Vercel robi to CDN)
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.get("/<path:filename>")
def static_files(filename):
    target = PUBLIC_DIR / filename
    if target.exists() and target.is_file():
        return send_from_directory(PUBLIC_DIR, filename)
    return send_from_directory(PUBLIC_DIR, "index.html")


# Vercel szuka obiektu `app` (WSGI). Lokalnie uruchamiamy serwer:
if __name__ == "__main__":
    port = int(os.getenv("APP_PORT", "8000"))
    print(f"[server] http://127.0.0.1:{port}  (PIN: {APP_PIN})")
    if not _has_real_data():
        print("[server] Tryb DEMO — dane przykładowe.")
    app.run(host="0.0.0.0", port=port, debug=False)
