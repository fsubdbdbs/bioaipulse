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
# Vercel: pliki projektu są dostępne z katalogu /var/task lub względem ROOT
for _p in [ROOT / "app", Path("/var/task/app"), Path("app")]:
    if _p.exists():
        sys.path.insert(0, str(_p))
        break
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
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _local_write(d: dict):
    LOCAL_STORE.parent.mkdir(parents=True, exist_ok=True)
    try:
        LOCAL_STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # Vercel read-only fs — ignoruj błąd zapisu


def store_get(key: str, default=None):
    if KV_URL and KV_TOKEN:
        try:
            import requests as _r
            # Upstash REST API: GET /get/{key}
            resp = _r.get(f"{KV_URL}/get/{key}",
                          headers={"Authorization": f"Bearer {KV_TOKEN}"}, timeout=8)
            if resp.ok:
                val = resp.json().get("result")
                if val is None:
                    return default
                return json.loads(val) if isinstance(val, str) else val
        except Exception:
            pass
        return default
    return _local_read().get(key, default)


def store_set(key: str, value):
    if KV_URL and KV_TOKEN:
        try:
            import requests as _r
            # Upstash REST API pipeline: POST / with [["SET", key, json_value]]
            serialized = json.dumps(value, ensure_ascii=False)
            _r.post(f"{KV_URL}",
                    headers={"Authorization": f"Bearer {KV_TOKEN}",
                             "Content-Type": "application/json"},
                    data=json.dumps([["SET", key, serialized]]), timeout=8)
        except Exception:
            pass
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

    custom_goal = store_get("custom_goal", None)
    custom_goals = {custom_goal["goal"]: custom_goal} if custom_goal else {}
    journal = store_get("journal", [])
    bundle = analytics.analyze(history, goal=goal, custom_goals=custom_goals, journal=journal)
    bundle["is_demo"] = is_demo
    if custom_goal:
        bundle["custom_goal"] = custom_goal
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

CHAT_SYSTEM = """Jesteś Pulse — osobisty AI coach zdrowia Franka. Polski, krótko, konkretnie. Max 3 zdania. Zero wstępów, zero powtarzania pytania, zero motywacyjnego lania wody.

Reagujesz na dane z opaski — zawsze cytuj liczby. Odpowiadasz na każde pytanie: trening, sen, HRV, odżywianie, cokolwiek.

ZMIANA CELU — działasz jak inteligentny system, nie Siri:
- Użytkownik może powiedzieć DOSŁOWNIE COKOLWIEK: brzuszki, skakanka, karate, taniec, spacery, golf, cokolwiek.
- Jest tylko JEDEN slot na cel użytkownika — ZAWSZE nadpisuje poprzedni. Nie tworzysz listy.
- Dopytaj max o 1 szczegół (jak często / jak długo). Potem USTAW cel.
- Przy potwierdzeniu dołącz na końcu (niewidoczny dla użytkownika):

<<SET_GOAL:{"goal":"ID","label":"Nazwa PL","emoji":"🎯","plan_hard":["zadanie","zadanie","zadanie"],"plan_mid":["zadanie","zadanie"],"plan_easy":["zadanie lekkie","zadanie"],"plan_headline_hard":"Nagłówek mocny","plan_headline_mid":"Nagłówek średni","plan_headline_easy":"Regeneracja","daily_task":"Jedno zadanie dnia","note":"szczegóły"}>>

Zasady ID: małe litery bez spacji (brzuszki, skakanka, karate, taniec_latino).
Emoji: zawsze trafne (🏋️🪢🥋🧗🕺🧘🤸🏇⛷️🎾🚵🤼🥊🎯).
KRYTYCZNE: bez bloku aplikacja NIE zmienia celu. Zawsze go dodaj przy potwierdzeniu."""


@app.post("/api/chat")
def api_chat():
    if not require_auth():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    messages = body.get("messages", [])
    goal = body.get("goal", "maintain")
    history, _ = load_history()
    custom_goal = store_get("custom_goal", None)
    custom_goals = {custom_goal["goal"]: custom_goal} if custom_goal else {}
    bundle = analytics.analyze(history, goal=goal, custom_goals=custom_goals) if history else {}
    today = bundle.get("today", {})
    ready = bundle.get("readiness", {})
    sleep = today.get("sleep") or {}
    base = bundle.get("baselines", {})

    def _avg(getter, n=7):
        vals = [v for v in (getter(e) for e in history[-n:]) if v is not None]
        return round(sum(vals)/len(vals), 1) if vals else None

    goal_data = bundle.get("goals_catalog", {}).get(goal, {})
    goal_label = goal_data.get("label", goal)
    ins = "; ".join(i["title"] for i in bundle.get("insights", [])) or "brak"
    res = bundle.get("resilience", {})
    week = bundle.get("weekly", {})
    eff = bundle.get("sleep_efficiency")
    vo2 = bundle.get("vo2max")

    # Dane z dziennika
    journal = store_get("journal", [])
    last_j = journal[-1] if journal else {}
    mood_vals = [e.get("mood") for e in journal[-7:] if e.get("mood")]
    avg_mood = round(sum(mood_vals)/len(mood_vals), 1) if mood_vals else None
    last_weight = next((e["weight_kg"] for e in reversed(journal) if e.get("weight_kg")), None)

    # Trend RHR 7 dni (opis)
    rhrs7 = [e.get("resting_hr_bpm") for e in history[-7:] if e.get("resting_hr_bpm")]
    rhr_trend = "stabilne" if not rhrs7 else ("rosnące" if rhrs7[-1] > rhrs7[0]+1 else "spadające" if rhrs7[-1] < rhrs7[0]-1 else "stabilne")
    hrvs7 = [e.get("hrv_rmssd") for e in history[-7:] if e.get("hrv_rmssd")]
    hrv_trend = "stabilne" if not hrvs7 else ("rosnące" if hrvs7[-1] > hrvs7[0]+2 else "spadające" if hrvs7[-1] < hrvs7[0]-2 else "stabilne")

    ctx = (
        f"[DANE FRANKA — {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')}]\n"
        f"Cel: {goal_label} | Readiness: {ready.get('score')}/100 ({ready.get('label')})\n"
        f"Sleep Score: {sleep.get('sleep_score')}/100, sen: {round((sleep.get('total_minutes') or 0)/60,1)}h"
        f"{f', wydajność snu: {eff}%' if eff else ''}\n"
        f"RHR: {today.get('resting_hr_bpm')} bpm (norma {base.get('rhr')}, trend 7d: {rhr_trend})\n"
        f"HRV: {today.get('hrv_rmssd')} ms (norma {base.get('hrv')}, trend 7d: {hrv_trend})\n"
        f"SpO2: {today.get('spo2_pct')}%, oddech: {today.get('respiration_rate')}/min, "
        f"temp.skóry: {today.get('skin_temp_variation_c')}°C, cardio load: {today.get('cardio_load')}\n"
        f"Kroki: {today.get('steps')}, AZM: {today.get('active_zone_minutes')} min, kcal: {today.get('calories_kcal')}\n"
        f"Tydzień: {week.get('total_steps')} kroków, {week.get('workouts_count')} treningów, "
        f"obciążenie {week.get('total_cardio_load')}/{week.get('cardio_load_target')} pkt\n"
        f"Odporność (resilience): {res.get('label')} ({res.get('score')}/100)\n"
        + (f"VO2Max szac.: {vo2} ml/kg/min\n" if vo2 else "")
        + (f"Waga: {last_weight} kg\n" if last_weight else "")
        + (f"Nastrój śr. 7 dni: {avg_mood}/5\n" if avg_mood else "")
        + f"Sygnały: {ins}\n"
        f"Śr. 30d: RHR {_avg(lambda e:e.get('resting_hr_bpm'),30)}, HRV {_avg(lambda e:e.get('hrv_rmssd'),30)}, "
        f"sen {_avg(lambda e:(e.get('sleep') or {}).get('total_minutes'),30)} min"
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
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile", messages=msgs,
                max_tokens=700,
                temperature=0.5,
            )
            reply = resp.choices[0].message.content
        except Exception as e:  # noqa: BLE001
            return jsonify({"reply": f"Błąd AI: {e}", "set_goal": None})
    else:
        reply = "Brak klucza GROQ_API_KEY — dodaj go do .env."

    # Wyciągnij SET_GOAL — JEDEN SLOT, zawsze nadpisuje.
    # Niezależnie od formatu: strip blok z odpowiedzi najpierw, potem parsuj.
    set_goal = None
    if "<<SET_GOAL:" in reply:
        # Bezpieczny strip: usuń wszystko od <<SET_GOAL: do końca linii / >>
        tag_start = reply.find("<<SET_GOAL:")
        raw_tag = reply[tag_start:]
        reply = reply[:tag_start].strip()
        # Spróbuj wyciągnąć JSON — obsłuż warianty z }>>, }}>> itp.
        m = re.search(r"<<SET_GOAL:(\{.+?\})\}*>>", raw_tag, re.S)
        if m:
            json_str = m.group(1)
            # Dokończ JSON jeśli obcięty
            try:
                payload = json.loads(json_str)
            except json.JSONDecodeError:
                # Spróbuj naprawić dodatkowe }
                json_str = re.sub(r'\}+$', '}', json_str.rstrip())
                try:
                    payload = json.loads(json_str)
                except json.JSONDecodeError:
                    payload = None
            if payload:
                gid = payload.get("goal", "").strip().lower().replace(" ", "_").replace("-", "_")
                if gid:
                    data = {
                        "goal":               gid,
                        "label":              payload.get("label", gid),
                        "emoji":              payload.get("emoji", "🎯"),
                        "custom":             True,
                        "plan_hard":          payload.get("plan_hard", []),
                        "plan_mid":           payload.get("plan_mid", []),
                        "plan_easy":          payload.get("plan_easy", []),
                        "plan_headline_hard": payload.get("plan_headline_hard", "Wysoka gotowość"),
                        "plan_headline_mid":  payload.get("plan_headline_mid", "Umiarkowanie"),
                        "plan_headline_easy": payload.get("plan_headline_easy", "Regeneracja"),
                        "daily_task":         payload.get("daily_task", ""),
                        "note":               payload.get("note", ""),
                    }
                    store_set("custom_goal", data)
                    set_goal = {"goal": gid, "label": data["label"], "emoji": data["emoji"]}

    # Fallback: model powiedział że ustawia cel ale pominął blok JSON
    # → drugi szybki call do Groq żeby wygenerować SET_GOAL
    GOAL_CONFIRM_KW = ["ustalam cel", "ustawiam cel", "potwierdzam cel", "nowy cel:",
                       "ustawiłem cel", "ustawiłam cel", "przełączam cel", "cel to:", "cel: "]
    if not set_goal and groq_key and any(kw in reply.lower() for kw in GOAL_CONFIRM_KW):
        try:
            from groq import Groq as _Groq
            _client = _Groq(api_key=groq_key)
            _resp = _client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": (
                        "Wygeneruj TYLKO poprawny JSON (bez tekstu wokół) dla nowego celu treningowego. "
                        'Format: {"goal":"id_bez_spacji","label":"Nazwa PL","emoji":"🎯",'
                        '"plan_hard":["ćw1","ćw2","ćw3"],"plan_mid":["ćw1","ćw2"],"plan_easy":["ćw1","ćw2"],'
                        '"plan_headline_hard":"Nagłówek","plan_headline_mid":"Nagłówek","plan_headline_easy":"Regeneracja",'
                        '"daily_task":"Główne zadanie dnia","note":""}'
                    )},
                    {"role": "user", "content": (
                        f"Wiadomość coacha: '{reply[:300]}'\n"
                        f"Kontekst rozmowy: '{' | '.join(m['content'][:60] for m in messages[-3:])}'\n"
                        "Wygeneruj JSON dla tego celu."
                    )},
                ],
                max_tokens=500, temperature=0.2,
            )
            _raw = _resp.choices[0].message.content.strip()
            _m = re.search(r"\{[\s\S]+\}", _raw)
            if _m:
                _payload = json.loads(_m.group())
                _gid = _payload.get("goal", "").strip().lower().replace(" ", "_")
                if _gid:
                    _data = {
                        "goal": _gid,
                        "label": _payload.get("label", _gid),
                        "emoji": _payload.get("emoji", "🎯"),
                        "custom": True,
                        "plan_hard":          _payload.get("plan_hard", []),
                        "plan_mid":           _payload.get("plan_mid", []),
                        "plan_easy":          _payload.get("plan_easy", []),
                        "plan_headline_hard": _payload.get("plan_headline_hard", "Wysoka gotowość"),
                        "plan_headline_mid":  _payload.get("plan_headline_mid", "Umiarkowanie"),
                        "plan_headline_easy": _payload.get("plan_headline_easy", "Regeneracja"),
                        "daily_task":         _payload.get("daily_task", ""),
                        "note":               _payload.get("note", ""),
                    }
                    store_set("custom_goal", _data)
                    set_goal = {"goal": _gid, "label": _data["label"], "emoji": _data["emoji"]}
        except Exception:
            pass

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
    try:
        from pywebpush import webpush
    except ImportError:
        return  # pywebpush opcjonalne (nie dostępne na Vercelu)
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


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------

@app.route("/api/journal", methods=["GET", "POST"])
def api_journal():
    if not require_auth():
        return jsonify({"error": "unauthorized"}), 401
    today_str = datetime.now(TZ).strftime("%Y-%m-%d")
    journal = store_get("journal", [])
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        date = data.get("date", today_str)
        entry = next((e for e in journal if e["date"] == date), None)
        if not entry:
            entry = {"date": date}
            journal.append(entry)
        for field in ["weight_kg","body_fat_pct","mood","mood_note",
                      "water_glasses","calories_eaten","protein_g","carbs_g","fat_g"]:
            if field in data:
                entry[field] = data[field]
        if "manual_workout" in data:
            wkts = entry.get("manual_workouts", [])
            wkts.append(data["manual_workout"])
            entry["manual_workouts"] = wkts
        journal.sort(key=lambda e: e["date"])
        journal = journal[-90:]
        store_set("journal", journal)
        return jsonify({"ok": True, "entry": entry})
    last_entry = next((e for e in reversed(journal) if e["date"] == today_str), {})
    return jsonify({"journal": journal[-30:], "today": last_entry})


@app.get("/api/journal/summary")
def api_journal_summary():
    if not require_auth():
        return jsonify({"error": "unauthorized"}), 401
    journal = store_get("journal", [])
    last30 = journal[-30:]
    weights = [(e["date"], e["weight_kg"]) for e in last30 if e.get("weight_kg")]
    moods = [(e["date"], e["mood"]) for e in last30 if e.get("mood")]
    return jsonify({
        "weights": weights, "moods": moods,
        "avg_mood": round(sum(m for _,m in moods)/len(moods), 1) if moods else None,
        "latest_weight": weights[-1][1] if weights else None,
        "bmi": round(weights[-1][1]/(1.78**2), 1) if weights else None,
        "manual_workouts_count": sum(len(e.get("manual_workouts",[])) for e in last30),
    })


# ---------------------------------------------------------------------------
# Workout Generator + Log
# ---------------------------------------------------------------------------

WORKOUT_PROMPT = """Trener personalny. Wygeneruj trening jako JSON. Odpowiedz TYLKO czystym JSON.
Format: {"title":"...","duration_min":45,"sections":[{"name":"Rozgrzewka","duration_min":8,"exercises":[{"name":"...","sets":2,"reps":"10","weight":"","rest_sec":30,"note":"..."}]},{"name":"Blok główny","duration_min":30,"exercises":[...]},{"name":"Schłodzenie","duration_min":7,"exercises":[...]}]}
Minimum 3 sekcje, minimum 3 ćwiczenia każda. Wszystko po polsku. JSON musi być poprawny i kompletny."""


@app.post("/api/workout/generate")
def api_workout_generate():
    if not require_auth():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    readiness_score = body.get("readiness_score", 70)
    intensity = "intensywny" if readiness_score>=75 else "umiarkowany" if readiness_score>=50 else "lekki"
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        return jsonify({"error": "Brak GROQ_API_KEY"}), 400
    try:
        from groq import Groq
        client = Groq(api_key=groq_key)
        prompt = (f"Trening: {body.get('type','ogólny')}, czas: {body.get('duration_min',45)} min, "
                  f"sprzęt: {body.get('equipment','brak')}, skupienie: {body.get('focus','całe ciało')}, "
                  f"poziom: {body.get('level','średni')}, intensywność: {intensity}.")
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"system","content":WORKOUT_PROMPT},{"role":"user","content":prompt}],
            max_tokens=1400, temperature=0.3,
        )
        raw = resp.choices[0].message.content.strip()
        m = re.search(r"\{[\s\S]+\}", raw)
        if m:
            return jsonify({"ok": True, "workout": json.loads(m.group())})
        return jsonify({"error": "Niepoprawny JSON z AI"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/workout/log")
def api_workout_log():
    if not require_auth():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    today_str = datetime.now(TZ).strftime("%Y-%m-%d")
    journal = store_get("journal", [])
    entry = next((e for e in journal if e["date"] == today_str), None)
    if not entry:
        entry = {"date": today_str}
        journal.append(entry)
    wkts = entry.get("manual_workouts", [])
    wkts.append({"type": body.get("title","Trening"), "duration_min": body.get("duration_min",0),
                  "rpe": body.get("rpe"), "calories": body.get("calories"),
                  "completed_at": datetime.now(TZ).isoformat()})
    entry["manual_workouts"] = wkts
    if body.get("rpe"):
        entry["rpe"] = body["rpe"]
    journal.sort(key=lambda e: e["date"])
    store_set("journal", journal)
    return jsonify({"ok": True})


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
