"""
analytics.py — Silnik analiz BioAI-Pulse

Zasada: jeśli opaska podaje gotowy wynik (Daily Readiness, Sleep Score) —
używamy GO BEZ przeliczania. Nasze analizy służą tylko do WYJAŚNIENIA
("co na to wpłynęło") oraz do rzeczy, których opaska nie liczy:
baseline, regularność snu, ostrzeżenia z trendów, plany działania pod cel.
"""

from __future__ import annotations

from datetime import datetime
from statistics import mean, pstdev


# ---------------------------------------------------------------------------
# Pomocnicze
# ---------------------------------------------------------------------------

def _sleep(e: dict) -> dict:
    return e.get("sleep") or {}


def _vals(history, getter):
    out = []
    for e in history:
        v = getter(e)
        if v is not None:
            out.append(v)
    return out


def _median(xs):
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

def baselines(history):
    past = history[:-1] if len(history) > 1 else history
    return {
        "rhr":   _median(_vals(past, lambda e: e.get("resting_hr_bpm"))),
        "hrv":   _median(_vals(past, lambda e: e.get("hrv_rmssd"))),
        "sleep": _median(_vals(past, lambda e: _sleep(e).get("total_minutes"))),
        "steps": _median(_vals(past, lambda e: e.get("steps"))),
        "spo2":  _median(_vals(past, lambda e: e.get("spo2_pct"))),
        "resp":  _median(_vals(past, lambda e: e.get("respiration_rate"))),
        "readiness": _median(_vals(past, lambda e: (e.get("daily_readiness") or {}).get("score"))),
        "sleep_score": _median(_vals(past, lambda e: _sleep(e).get("sleep_score"))),
    }


# ---------------------------------------------------------------------------
# Readiness — bierzemy wprost z urządzenia, dodajemy tylko wyjaśnienie
# ---------------------------------------------------------------------------

def readiness(entry, base):
    dev = entry.get("daily_readiness") or {}
    score = dev.get("score")
    label = dev.get("label")

    if score is None:
        return {"score": None, "label": "brak danych", "source": "none",
                "summary": "Opaska nie przekazała wyniku gotowości."}

    if score >= 80:
        summary = "Organizm dobrze zregenerowany — możesz pozwolić sobie na mocniejszy trening."
    elif score >= 60:
        summary = "Solidna forma. Trenuj normalnie, ale słuchaj ciała."
    elif score >= 40:
        summary = "Regeneracja niepełna — lepiej lżejszy dzień."
    else:
        summary = "Niska gotowość. Organizm potrzebuje odpoczynku."

    return {"score": score, "label": label or "", "source": "device", "summary": summary}


def readiness_factors(entry, base):
    """Jakościowe wyjaśnienie — co podbiło/obniżyło gotowość. NIE sumuje się do wyniku."""
    out = []
    total = _sleep(entry).get("total_minutes")
    if total is not None:
        h = total / 60
        st = "good" if h >= 7.5 else "ok" if h >= 6.5 else "bad"
        out.append({"name": "Sen", "status": st, "note": f"{h:.1f}h"})
    ss = _sleep(entry).get("sleep_score")
    if ss is not None:
        st = "good" if ss >= 80 else "ok" if ss >= 60 else "bad"
        out.append({"name": "Sleep Score", "status": st, "note": f"{ss}/100"})
    hrv = entry.get("hrv_rmssd")
    if hrv is not None and base.get("hrv"):
        d = hrv - base["hrv"]
        st = "good" if d >= 3 else "ok" if d >= -5 else "bad"
        out.append({"name": "HRV", "status": st, "note": f"{hrv:.0f}ms ({d:+.0f} vs norma)"})
    rhr = entry.get("resting_hr_bpm")
    if rhr is not None and base.get("rhr"):
        d = rhr - base["rhr"]
        st = "good" if d <= -1 else "ok" if d <= 4 else "bad"
        out.append({"name": "Tętno spocz.", "status": st, "note": f"{rhr:.0f} ({d:+.0f})"})
    skin = entry.get("skin_temp_variation_c")
    if skin is not None:
        st = "good" if abs(skin) <= 0.3 else "ok" if abs(skin) <= 0.6 else "bad"
        out.append({"name": "Temp. skóry", "status": st, "note": f"{skin:+.1f}°C"})
    return out


# ---------------------------------------------------------------------------
# Regularność snu
# ---------------------------------------------------------------------------

def sleep_consistency(history):
    starts = []
    for e in history[-14:]:
        s = _sleep(e).get("sleep_start")
        if not s:
            continue
        try:
            dt = datetime.fromisoformat(s)
            m = dt.hour * 60 + dt.minute
            if m > 12 * 60:
                m -= 24 * 60
            starts.append(m)
        except ValueError:
            continue
    if len(starts) < 3:
        return None
    sd = pstdev(starts)
    avg = (mean(starts) + 1440) % 1440
    label = ("Bardzo regularny" if sd <= 30 else "Regularny" if sd <= 60
             else "Umiarkowanie nieregularny" if sd <= 90 else "Nieregularny")
    return {"stddev_min": round(sd), "avg_bedtime": f"{int(avg)//60:02d}:{int(avg)%60:02d}", "label": label}


# ---------------------------------------------------------------------------
# Insights / ostrzeżenia
# ---------------------------------------------------------------------------

def insights(history, base):
    out = []
    if len(history) < 3:
        return out
    last3 = history[-3:]
    today = history[-1]

    rhrs = _vals(last3, lambda e: e.get("resting_hr_bpm"))
    if len(rhrs) == 3 and rhrs[0] < rhrs[1] < rhrs[2]:
        out.append({"type": "warning", "icon": "⚠️", "title": "Tętno spoczynkowe rośnie 3 dni z rzędu",
                    "text": f"{rhrs[0]:.0f} → {rhrs[1]:.0f} → {rhrs[2]:.0f} bpm. Częsty sygnał przemęczenia lub nadchodzącej infekcji."})

    hrvs = _vals(last3, lambda e: e.get("hrv_rmssd"))
    if len(hrvs) == 3 and hrvs[0] > hrvs[1] > hrvs[2]:
        out.append({"type": "warning", "icon": "📉", "title": "HRV spada 3 dni z rzędu",
                    "text": f"{hrvs[0]:.0f} → {hrvs[1]:.0f} → {hrvs[2]:.0f} ms. Układ nerwowy nie nadąża z regeneracją."})

    short = [s for s in _vals(last3, lambda e: _sleep(e).get("total_minutes")) if s < 360]
    if len(short) >= 2:
        out.append({"type": "warning", "icon": "😴", "title": "Niedobór snu",
                    "text": "Co najmniej 2 z 3 ostatnich nocy poniżej 6h. Deficyt snu kumuluje się."})

    skin = today.get("skin_temp_variation_c")
    if skin is not None and skin >= 0.5:
        out.append({"type": "warning", "icon": "🌡️", "title": "Podwyższona temperatura skóry",
                    "text": f"{skin:+.1f}°C względem Twojej normy. Czasem wczesny sygnał infekcji — obserwuj."})

    spo2 = today.get("spo2_pct")
    if spo2 is not None and spo2 < 94:
        out.append({"type": "warning", "icon": "🫁", "title": "Niższe natlenienie (SpO2)",
                    "text": f"SpO2 {spo2}% w nocy. Pojedynczy odczyt nie jest groźny, ale warto obserwować."})

    week = history[-7:]
    steps = _vals(week, lambda e: e.get("steps"))
    if steps and base.get("steps") and mean(steps) > base["steps"] * 1.1:
        out.append({"type": "good", "icon": "🔥", "title": "Aktywność powyżej Twojej normy",
                    "text": f"Średnio {mean(steps):,.0f} kroków/dzień w tym tygodniu. Trzymaj tempo."})

    hrv = today.get("hrv_rmssd")
    if hrv and base.get("hrv") and hrv > base["hrv"] + 5:
        out.append({"type": "good", "icon": "💪", "title": "Świetna regeneracja",
                    "text": f"HRV dziś {hrv:.0f}ms, powyżej normy. Dobry dzień na mocniejszy trening."})

    return out


# ---------------------------------------------------------------------------
# Plany działania — zależne od CELU (goal)
# ---------------------------------------------------------------------------

GOALS = {
    "maintain":   {"label": "Utrzymanie formy", "emoji": "⚖️"},
    "running":    {"label": "Bieganie", "emoji": "🏃"},
    "cycling":    {"label": "Rower", "emoji": "🚴"},
    "swimming":   {"label": "Pływanie", "emoji": "🏊"},
    "strength":   {"label": "Siła", "emoji": "🏋️"},
    "weight_loss":{"label": "Redukcja wagi", "emoji": "🔥"},
    "sleep":      {"label": "Lepszy sen", "emoji": "😴"},
}


def action_plans(entry, ready, base, goal="maintain"):
    score = ready.get("score") or 50
    total = _sleep(entry).get("total_minutes")
    sleep_h = total / 60 if total else None

    # Plan 1: utrzymaj
    maintain = ["Trzymaj stałe pory snu (±30 min).", "8 000–10 000 kroków rozłożone w ciągu dnia."]
    if sleep_h and sleep_h >= 7:
        maintain.insert(0, f"Sen {sleep_h:.1f}h jest dobry — pilnuj go.")

    # Plan 2: popraw najsłabszy element
    factors = readiness_factors(entry, base)
    weakest = min(factors, key=lambda f: {"bad": 0, "ok": 1, "good": 2}[f["status"]]) if factors else None
    improve = []
    if weakest:
        nm = weakest["name"]
        if "Sen" in nm or "Sleep" in nm:
            improve = ["Cel: +45 min snu. Wygaś ekrany 60 min przed snem.", "Ostatnia kawa ≥8h przed snem.", "Sypialnia 18–19°C, ciemno."]
        elif nm == "HRV":
            improve = ["Dziś trening regeneracyjny zamiast intensywnego.", "10 min oddychania 4-7-8 wieczorem.", "Nawodnienie, bez alkoholu."]
        elif "Tętno" in nm:
            improve = ["Odpuść interwały, spokojne cardio.", "Więcej wody i elektrolitów.", "Jeśli jutro też wysokie — dzień wolny."]
        elif "Temp" in nm:
            improve = ["Podwyższona temp. skóry — odpuść mocny trening.", "Więcej snu i płynów.", "Obserwuj, czy nie idzie infekcja."]
    if not improve:
        improve = ["Dorzuć 1 trening więcej niż zwykle.", "Zwiększ cel kroków o 1 000."]

    # Plan 3: SPORT — dobrany do CELU i gotowości
    sport = _sport_plan(goal, score)

    return [
        {"id": "maintain", "title": "Utrzymaj", "icon": "⚖️", "items": maintain},
        {"id": "improve", "title": "Popraw się", "icon": "📈", "items": improve},
        {"id": "sport", "title": "Trening", "icon": GOALS.get(goal, GOALS["maintain"])["emoji"], "headline": sport[0], "items": sport[1]},
    ]


def _sport_plan(goal, score):
    hard = score >= 75
    mid = 50 <= score < 75
    if goal == "swimming":
        if hard:
            return ("Basen — interwały", ["Rozgrzewka 200m spokojnie, potem 6×50m mocno / 30s przerwy.", "Schłodzenie 100m na wznak.", "Nawodnienie — w wodzie nie czujesz potu, ale się pocisz."])
        if mid:
            return ("Basen — spokojny dystans", ["30–45 min w spokojnym, stałym tempie.", "Skup się na technice — długi wyciąg, głowa w dół.", "Naprzemiennie krol i grzbiet."])
        return ("Basen — regeneracja", ["15–20 min spokojnego pływania, mocno odpuść.", "Ruch w wodzie pomaga regeneracji — delikatne tempo.", "Unikaj mocnych sprintów dziś."])
    if goal == "running":
        if hard:
            return ("Bieg — dzień jakościowy", ["Rozbieganie 10 min + 6×400 m szybko / 200 m trucht.", "Rozciąganie łydek i bioder po.", "Nawodnienie i białko w 30 min po."])
        if mid:
            return ("Bieg spokojny (strefa 2)", ["30–40 min w tempie rozmownym.", "Skup się na kadencji ~170–180.", "Bez przyspieszania na końcu."])
        return ("Regeneracja", ["Spacer 30 min zamiast biegu.", "Mobilność bioder i kostek.", "Bieganie jutro."])
    if goal == "cycling":
        if hard:
            return ("Rower — interwały", ["5×3 min mocno / 3 min luźno.", "Rozgrzewka 15 min, schłodzenie 10 min.", "Elektrolity na trasę."])
        if mid:
            return ("Rower spokojnie", ["45–60 min strefa 2.", "Stała kadencja 85–95.", "Bez sprintów."])
        return ("Lekko / regeneracja", ["Spokojne 30 min lub wolne.", "Rozciąganie.", "Mocniej jutro."])
    if goal == "strength":
        if hard:
            return ("Siłownia — dzień ciężki", ["Główny bój 4–5 serii, technika ponad ciężar.", "Akcesoria 3×10–12.", "Białko 1.6–2 g/kg dziś."])
        if mid:
            return ("Siłownia — umiarkowanie", ["Ciężar ~70%, więcej powtórzeń.", "Skup na tempie i kontroli.", "Dobra rozgrzewka."])
        return ("Lekko / mobilność", ["Trening mobilności 20 min.", "Lekkie GPP / core.", "Ciężko jutro."])
    if goal == "weight_loss":
        if hard:
            return ("Spalanie — dzień mocniejszy", ["45–60 min cardio strefa 2–3 + 10 min interwałów.", "Cel kroków: 12 000.", "Deficyt ~300–500 kcal, dużo białka."])
        if mid:
            return ("Spalanie — umiarkowanie", ["40 min szybki marsz / rower.", "Cel kroków: 10 000.", "Pilnuj białka i wody."])
        return ("Lekko, ale w ruchu", ["Długi spacer 45 min.", "Cel kroków: 8 000.", "Nie podkręcaj, regeneruj."])
    if goal == "sleep":
        return ("Priorytet: sen", ["Stała pora snu — dziś połóż się o tej samej godzinie.", "Bez ekranów 60 min przed.", "Lekki trening max do wczesnego wieczora."])
    # maintain
    if hard:
        return ("Zielone światło na wysiłek", ["Mocniejszy trening wg uznania.", "Albo bieg tempowy 30–40 min.", "Technika przede wszystkim."])
    if mid:
        return ("Umiarkowany wysiłek", ["Spokojne cardio 45 min strefa 2.", "Albo trucht + mobilność.", "Bez maksymalnych interwałów."])
    return ("Dzień regeneracji", ["Spacer 30–40 min.", "Rozciąganie / joga 15 min.", "Sen priorytetem."])


# ---------------------------------------------------------------------------
# Główna funkcja
# ---------------------------------------------------------------------------

def daily_goals(entry, base, goal="maintain") -> list[dict]:
    """Konkretne zadania na dziś — generowane z danych, dopasowane do celu."""
    tasks = []
    score = (entry.get("daily_readiness") or {}).get("score") or 50
    sleep_min = _sleep(entry).get("total_minutes") or 0
    steps = entry.get("steps") or 0
    hrv = entry.get("hrv_rmssd")
    rhr = entry.get("resting_hr_bpm")
    base_rhr = base.get("rhr")

    # Cel treningowy — dobrany do sportu + gotowości
    if goal == "swimming":
        if score >= 75:
            tasks.append({"id":"swim","text":"Basen: 6×50m interwałów + rozgrzewka 200m","cat":"trening","icon":"🏊"})
        else:
            tasks.append({"id":"swim","text":"Basen: 30 min spokojny dystans, fokus na technice","cat":"trening","icon":"🏊"})
    elif goal == "running":
        tasks.append({"id":"run","text":"Bieg "+("30–40 min tempo" if score>=75 else "20–30 min strefa 2"),"cat":"trening","icon":"🏃"})
    elif goal == "cycling":
        tasks.append({"id":"bike","text":"Rower "+("interwały 5×3 min" if score>=75 else "45 min strefa 2"),"cat":"trening","icon":"🚴"})
    elif goal == "strength":
        tasks.append({"id":"gym","text":"Siłownia: "+("ciężki dzień główne ćwiczenia" if score>=75 else "średnia intensywność, technika"),"cat":"trening","icon":"🏋️"})
    elif goal == "weight_loss":
        tasks.append({"id":"cardio","text":"Cardio 40–50 min + cel 12 000 kroków","cat":"trening","icon":"🔥"})
    elif goal == "sleep":
        tasks.append({"id":"bedtime","text":"Połóż się spać przed 23:00 (stała pora)","cat":"sen","icon":"🌙"})
    else:
        if score >= 75:
            tasks.append({"id":"train","text":"Dowolny trening 30–45 min","cat":"trening","icon":"💪"})
        else:
            tasks.append({"id":"walk","text":"Spacer 30 min — regeneracja","cat":"ruch","icon":"🚶"})

    # Kroki
    steps_goal = 12000 if goal == "weight_loss" else 8000
    if steps < steps_goal:
        tasks.append({"id":"steps","text":f"Dojdź do {steps_goal:,} kroków (masz {steps:,})".replace(",","."),"cat":"ruch","icon":"👟"})

    # Woda — zawsze
    tasks.append({"id":"water","text":"Wypij min. 2 litry wody","cat":"zdrowie","icon":"💧"})

    # Sen jeśli niedobór
    if sleep_min < 390:
        tasks.append({"id":"sleep","text":"Dziś połóż się wcześniej — dobierz sen","cat":"sen","icon":"😴"})

    # HRV/RHR — regeneracja
    if hrv and base.get("hrv") and hrv < base["hrv"] - 8:
        tasks.append({"id":"relax","text":"10 min oddychania 4-7-8 wieczorem (HRV poniżej normy)","cat":"regeneracja","icon":"🧘"})
    if rhr and base_rhr and rhr > base_rhr + 5:
        tasks.append({"id":"recovery","text":"Unikaj intensywności — tętno podwyższone","cat":"regeneracja","icon":"❤️"})

    # Pływanie — stroje suche po wyjściu
    if goal == "swimming":
        tasks.append({"id":"swim_prep","text":"Spakuj torbę na basen","cat":"przygotowanie","icon":"🎒"})

    return tasks


def analyze(history, goal="maintain"):
    if not history:
        return {"empty": True}
    base = baselines(history)
    today = history[-1]
    ready = readiness(today, base)
    return {
        "empty": False,
        "today": today,
        "baselines": base,
        "readiness": ready,
        "readiness_factors": readiness_factors(today, base),
        "consistency": sleep_consistency(history),
        "insights": insights(history, base),
        "action_plans": action_plans(today, ready, base, goal),
        "daily_goals": daily_goals(today, base, goal),
        "goal": goal,
        "goals_catalog": GOALS,
        "history": history,
    }
