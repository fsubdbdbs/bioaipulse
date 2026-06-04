"""
analytics.py — Silnik analiz BioAI-Pulse

Zasada: jeśli opaska podaje gotowy wynik (Daily Readiness, Sleep Score) —
używamy GO BEZ przeliczania. Nasze analizy służą tylko do WYJAŚNIENIA
("co na to wpłynęło") oraz do rzeczy, których opaska nie liczy:
baseline, regularność snu, ostrzeżenia z trendów, plany działania pod cel.

Cele są w pełni dynamiczne — coach AI tworzy dowolny cel z planem,
który jest tu przechowywany i używany do generowania planów i zadań.
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
# Katalog celów — predefiniowane + dynamiczne od coacha
# ---------------------------------------------------------------------------

GOALS = {
    "maintain":   {"label": "Utrzymanie formy", "emoji": "⚖️"},
    "running":    {"label": "Bieganie",          "emoji": "🏃"},
    "cycling":    {"label": "Rower",             "emoji": "🚴"},
    "swimming":   {"label": "Pływanie",          "emoji": "🏊"},
    "strength":   {"label": "Siła",              "emoji": "🏋️"},
    "weight_loss":{"label": "Redukcja wagi",     "emoji": "🔥"},
    "sleep":      {"label": "Lepszy sen",        "emoji": "😴"},
}


def build_goals_catalog(custom_goals: dict = None) -> dict:
    """Łączy predefiniowane cele z dynamicznymi stworzonymi przez coacha."""
    catalog = {k: dict(v) for k, v in GOALS.items()}
    if custom_goals:
        for gid, gdata in custom_goals.items():
            catalog[gid] = {
                "label":              gdata.get("label", gid),
                "emoji":              gdata.get("emoji", "🎯"),
                "custom":             True,
                "plan_hard":          gdata.get("plan_hard", []),
                "plan_mid":           gdata.get("plan_mid", []),
                "plan_easy":          gdata.get("plan_easy", []),
                "plan_headline_hard": gdata.get("plan_headline_hard", "Wysoka gotowość"),
                "plan_headline_mid":  gdata.get("plan_headline_mid", "Umiarkowanie"),
                "plan_headline_easy": gdata.get("plan_headline_easy", "Regeneracja"),
                "daily_task":         gdata.get("daily_task", ""),
            }
    return catalog


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

def baselines(history):
    past = history[:-1] if len(history) > 1 else history
    return {
        "rhr":         _median(_vals(past, lambda e: e.get("resting_hr_bpm"))),
        "hrv":         _median(_vals(past, lambda e: e.get("hrv_rmssd"))),
        "sleep":       _median(_vals(past, lambda e: _sleep(e).get("total_minutes"))),
        "steps":       _median(_vals(past, lambda e: e.get("steps"))),
        "spo2":        _median(_vals(past, lambda e: e.get("spo2_pct"))),
        "resp":        _median(_vals(past, lambda e: e.get("respiration_rate"))),
        "readiness":   _median(_vals(past, lambda e: (e.get("daily_readiness") or {}).get("score"))),
        "sleep_score": _median(_vals(past, lambda e: _sleep(e).get("sleep_score"))),
    }


# ---------------------------------------------------------------------------
# Readiness — wprost z urządzenia
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
# Insights
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
                    "text": f"{rhrs[0]:.0f} → {rhrs[1]:.0f} → {rhrs[2]:.0f} bpm. Częsty sygnał przemęczenia lub infekcji."})

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
                    "text": f"{skin:+.1f}°C względem normy. Możliwy wczesny sygnał infekcji."})

    spo2 = today.get("spo2_pct")
    if spo2 is not None and spo2 < 94:
        out.append({"type": "warning", "icon": "🫁", "title": "Niższe natlenienie (SpO2)",
                    "text": f"SpO2 {spo2}% w nocy. Warto obserwować."})

    week = history[-7:]
    steps = _vals(week, lambda e: e.get("steps"))
    if steps and base.get("steps") and mean(steps) > base["steps"] * 1.1:
        out.append({"type": "good", "icon": "🔥", "title": "Aktywność powyżej normy",
                    "text": f"Średnio {mean(steps):,.0f} kroków/dzień — powyżej Twojej normy.".replace(",", " ")})

    hrv = today.get("hrv_rmssd")
    if hrv and base.get("hrv") and hrv > base["hrv"] + 5:
        out.append({"type": "good", "icon": "💪", "title": "Świetna regeneracja",
                    "text": f"HRV dziś {hrv:.0f}ms — powyżej Twojej normy. Dobry dzień na mocny trening."})

    return out


# ---------------------------------------------------------------------------
# Plany działania — w pełni dynamiczne (z katalogu celu)
# ---------------------------------------------------------------------------

def action_plans(entry, ready, base, goal="maintain", goals_catalog: dict = None):
    score = ready.get("score") or 50
    total = _sleep(entry).get("total_minutes")
    sleep_h = total / 60 if total else None
    catalog = goals_catalog or build_goals_catalog()

    # Plan 1: Utrzymaj
    maintain = ["Trzymaj stałe pory snu (±30 min).", "8 000–10 000 kroków w ciągu dnia."]
    if sleep_h and sleep_h >= 7:
        maintain.insert(0, f"Sen {sleep_h:.1f}h jest dobry — pilnuj go.")

    # Plan 2: Popraw najsłabszy element
    factors = readiness_factors(entry, base)
    weakest = min(factors, key=lambda f: {"bad": 0, "ok": 1, "good": 2}[f["status"]]) if factors else None
    improve = []
    if weakest:
        nm = weakest["name"]
        if "Sen" in nm or "Sleep" in nm:
            improve = ["Cel: +45 min snu. Wygaś ekrany 60 min przed snem.", "Ostatnia kawa ≥8h przed snem.", "Sypialnia 18–19°C, ciemno."]
        elif nm == "HRV":
            improve = ["Dziś trening regeneracyjny.", "10 min oddychania 4-7-8 wieczorem.", "Nawodnienie, bez alkoholu."]
        elif "Tętno" in nm:
            improve = ["Odpuść interwały, spokojne cardio.", "Więcej wody i elektrolitów.", "Jeśli jutro też wysokie — dzień wolny."]
        elif "Temp" in nm:
            improve = ["Odpuść mocny trening.", "Więcej snu i płynów.", "Obserwuj, czy nie idzie infekcja."]
    if not improve:
        improve = ["Dorzuć 1 trening więcej niż zwykle.", "Zwiększ cel kroków o 1 000."]

    # Plan 3: Trening — z dynamicznego katalogu
    goal_data = catalog.get(goal) or catalog.get("maintain", {})
    sport_headline, sport_items = _sport_plan(score, goal_data)
    goal_emoji = goal_data.get("emoji", "🎯")

    return [
        {"id": "maintain", "title": "Utrzymaj",  "icon": "⚖️",        "items": maintain},
        {"id": "improve",  "title": "Popraw się", "icon": "📈",        "items": improve},
        {"id": "sport",    "title": "Trening",    "icon": goal_emoji,  "headline": sport_headline, "items": sport_items},
    ]


def _sport_plan(score: int, goal_data: dict):
    """
    Generuje plan sportowy z danych celu.
    Dynamiczne cele (stworzone przez coacha) mają wbudowane plan_hard/mid/easy.
    Predefiniowane cele mają swoje wbudowane plany jako fallback.
    """
    hard = score >= 75
    mid  = 50 <= score < 75

    # Cel dynamiczny od coacha — użyj jego planów bezpośrednio
    if goal_data.get("plan_hard") and goal_data.get("plan_mid"):
        if hard:
            return (goal_data.get("plan_headline_hard", "Wysoka gotowość"),
                    goal_data["plan_hard"])
        if mid:
            return (goal_data.get("plan_headline_mid", "Umiarkowanie"),
                    goal_data["plan_mid"])
        return (goal_data.get("plan_headline_easy", "Regeneracja"),
                goal_data.get("plan_easy", ["Odpoczynek i lekki ruch."]))

    # Predefiniowane cele — fallback wbudowany
    label = goal_data.get("label", "")
    emoji = goal_data.get("emoji", "")

    if emoji == "🏃" or "Biegan" in label:
        if hard:  return ("Bieg — dzień jakościowy", ["6×400 m szybko / 200 m trucht.", "Rozciąganie po.", "Białko w 30 min po."])
        if mid:   return ("Bieg spokojny (strefa 2)", ["30–40 min w tempie rozmownym.", "Kadencja ~170–180 spm.", "Bez przyspieszania na końcu."])
        return ("Regeneracja", ["Spacer 30 min zamiast biegu.", "Mobilność.", "Bieganie jutro."])

    if emoji == "🚴" or "Rower" in label:
        if hard:  return ("Rower — interwały", ["5×3 min mocno / 3 min luźno.", "Elektrolity.", "Schłodzenie 10 min."])
        if mid:   return ("Rower spokojnie", ["45–60 min strefa 2.", "Kadencja 85–95.", "Bez sprintów."])
        return ("Lekko", ["Spokojne 30 min.", "Rozciąganie.", "Mocniej jutro."])

    if emoji == "🏊" or "Pływan" in label:
        if hard:  return ("Basen — interwały", ["6×50 m mocno / 30 s przerwy.", "Schłodzenie 100 m na wznak.", "Nawodnienie."])
        if mid:   return ("Basen — dystans", ["30–45 min spokojne tempo.", "Fokus na technice.", "Naprzemiennie krol i grzbiet."])
        return ("Basen — regeneracja", ["15–20 min bardzo spokojnie.", "Delikatne tempo.", "Unikaj sprintów."])

    if emoji == "🏋️" or "Siła" in label:
        if hard:  return ("Siłownia — dzień ciężki", ["4–5 serii, technika ponad ciężar.", "Akcesoria 3×10–12.", "Białko 1.6–2 g/kg."])
        if mid:   return ("Siłownia — umiarkowanie", ["Ciężar ~70%, więcej powtórzeń.", "Fokus na tempie.", "Dobra rozgrzewka."])
        return ("Mobilność", ["Trening mobilności 20 min.", "Lekkie core.", "Ciężko jutro."])

    if emoji == "🔥" or "Redukcja" in label or "wagi" in label.lower():
        if hard:  return ("Spalanie — mocno", ["45 min cardio + 10 min interwałów.", "Cel 12 000 kroków.", "Deficyt ~400 kcal."])
        if mid:   return ("Spalanie — umiarkowanie", ["40 min marsz / rower.", "Cel 10 000 kroków.", "Pilnuj białka."])
        return ("Lekko, ale w ruchu", ["Spacer 45 min.", "Cel 8 000 kroków.", "Regeneruj."])

    if emoji == "😴" or "sen" in label.lower():
        return ("Priorytet: sen", ["Połóż się przed 23:00.", "Bez ekranów 60 min przed.", "Lekki trening max do wczesnego wieczora."])

    # maintain / nieznany
    if hard:  return ("Zielone światło", ["Mocniejszy trening wg uznania.", "Bieg tempowy 30–40 min.", "Technika przede wszystkim."])
    if mid:   return ("Umiarkowany wysiłek", ["Spokojne cardio 45 min.", "Trucht + mobilność.", "Bez max interwałów."])
    return ("Regeneracja", ["Spacer 30–40 min.", "Rozciąganie / joga.", "Sen priorytetem."])


# ---------------------------------------------------------------------------
# Zadania na dziś — dynamiczne (z katalogu celu)
# ---------------------------------------------------------------------------

def daily_goals(entry, base, goal="maintain", goals_catalog: dict = None) -> list[dict]:
    """Konkretne zadania na dziś, dopasowane do aktywnego celu i danych."""
    tasks = []
    catalog = goals_catalog or build_goals_catalog()
    goal_data = catalog.get(goal) or {}
    score = (entry.get("daily_readiness") or {}).get("score") or 50
    sleep_min = _sleep(entry).get("total_minutes") or 0
    steps = entry.get("steps") or 0
    hrv = entry.get("hrv_rmssd")
    rhr = entry.get("resting_hr_bpm")
    base_rhr = base.get("rhr")
    emoji = goal_data.get("emoji", "🎯")
    label = goal_data.get("label", goal)

    # Główne zadanie treningowe — z dynamicznego celu lub wbudowane
    if goal_data.get("daily_task"):
        # Cel dynamiczny — zadanie stworzone przez coacha
        task_text = goal_data["daily_task"]
        if score < 50:
            task_text += " (lżej — regeneracja)"
        tasks.append({"id": "main_goal", "text": task_text, "cat": "trening", "icon": emoji})
    elif goal == "running":
        tasks.append({"id":"run","text":"Bieg "+("30–40 min tempo" if score>=75 else "20–30 min strefa 2"),"cat":"trening","icon":"🏃"})
    elif goal == "cycling":
        tasks.append({"id":"bike","text":"Rower "+("interwały 5×3 min" if score>=75 else "45 min strefa 2"),"cat":"trening","icon":"🚴"})
    elif goal == "swimming":
        tasks.append({"id":"swim","text":"Basen: "+("6×50m interwałów + rozgrzewka 200m" if score>=75 else "30 min spokojny dystans"),"cat":"trening","icon":"🏊"})
    elif goal == "strength":
        tasks.append({"id":"gym","text":"Siłownia: "+("ciężki dzień" if score>=75 else "średnia intensywność, technika"),"cat":"trening","icon":"🏋️"})
    elif goal == "weight_loss":
        tasks.append({"id":"cardio","text":"Cardio 40–50 min + cel 12 000 kroków","cat":"trening","icon":"🔥"})
    elif goal == "sleep":
        tasks.append({"id":"bedtime","text":"Połóż się spać przed 23:00 (stała pora)","cat":"sen","icon":"🌙"})
    else:
        tasks.append({"id":"train","text":("Trening 30–45 min" if score>=75 else "Spacer 30 min — regeneracja"),"cat":"ruch","icon":"💪"})

    # Kroki
    steps_goal = 12000 if goal == "weight_loss" else 8000
    if steps < steps_goal:
        tasks.append({"id":"steps","text":f"Dojdź do {steps_goal} kroków (masz {steps})","cat":"ruch","icon":"👟"})

    # Woda — zawsze
    tasks.append({"id":"water","text":"Wypij min. 2 litry wody","cat":"zdrowie","icon":"💧"})

    # Sen jeśli niedobór
    if sleep_min < 390:
        tasks.append({"id":"sleep_more","text":"Dziś połóż się wcześniej — dobierz sen","cat":"sen","icon":"😴"})

    # HRV / RHR ostrzeżenie
    if hrv and base.get("hrv") and hrv < base["hrv"] - 8:
        tasks.append({"id":"relax","text":"10 min oddychania 4-7-8 wieczorem (HRV poniżej normy)","cat":"regeneracja","icon":"🧘"})
    if rhr and base_rhr and rhr > base_rhr + 5:
        tasks.append({"id":"recovery","text":"Unikaj intensywności — tętno podwyższone","cat":"regeneracja","icon":"❤️"})

    return tasks


# ---------------------------------------------------------------------------
# Główna funkcja
# ---------------------------------------------------------------------------

def analyze(history, goal="maintain", custom_goals: dict = None):
    if not history:
        return {"empty": True}
    catalog = build_goals_catalog(custom_goals)
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
        "action_plans": action_plans(today, ready, base, goal, goals_catalog=catalog),
        "daily_goals": daily_goals(today, base, goal, goals_catalog=catalog),
        "goal": goal,
        "goals_catalog": catalog,
        "history": history,
    }
