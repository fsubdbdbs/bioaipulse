"""
demo_data.py — Generator realistycznych danych demo BioAI-Pulse

Tworzy 30 dni danych obejmujących WSZYSTKIE pola, które daje opaska Fitbit:
aktywność, serce 24/7, sen (ze Sleep Score), SpO2, oddech, temperatura skóry,
obciążenie kardio, Daily Readiness Score, treningi z trasą GPS.

Wartości typu Sleep Score i Daily Readiness są "z urządzenia" — apka używa ich
bez przeliczania (tak jak prawdziwa opaska).

Użycie:
  python3 app/demo_data.py            # zapisuje data/demo_metrics.json
"""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

random.seed(7)  # powtarzalne demo

TZ = timezone(timedelta(hours=2))  # CEST — żeby godziny snu wyglądały realnie
OUT = Path(__file__).resolve().parent.parent / "data" / "demo_metrics.json"

# Gdynia — punkt startowy tras treningowych
GDYNIA = (54.5189, 18.5305)


def iso(dt: datetime) -> str:
    return dt.astimezone(TZ).isoformat()


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Trasa GPS (prosty spacerowy polyline w okolicy Gdyni)
# ---------------------------------------------------------------------------

def gen_route(n: int, dist_km: float) -> list[list[float]]:
    lat, lng = GDYNIA
    step = (dist_km / n) / 111.0  # ~stopnie na punkt
    pts = [[round(lat, 5), round(lng, 5)]]
    ang = random.uniform(0, math.tau)
    for _ in range(n):
        ang += random.uniform(-0.5, 0.5)
        lat += math.sin(ang) * step
        lng += math.cos(ang) * step * 1.6
        pts.append([round(lat, 5), round(lng, 5)])
    return pts


def gen_workout(date: datetime, kind: str) -> dict:
    presets = {
        "Bieg":   (28, 5.2, 152, 178, 0.06),
        "Rower":  (52, 21.0, 134, 165, 0.025),
        "Spacer": (40, 3.4, 98, 120, 0.0),
        "Siłownia": (45, 0.0, 118, 150, None),
    }
    dur, dist, avg_hr, max_hr, kcal_per = presets[kind]
    dur = dur + random.randint(-6, 10)
    dist = round(dist * random.uniform(0.85, 1.15), 2) if dist else 0
    start = date.replace(hour=random.randint(7, 19), minute=random.choice([0, 15, 30]), second=0, microsecond=0)
    pace = round(dur / dist, 2) if dist else None
    elev = random.randint(5, 60) if dist else 0
    route = gen_route(40, dist) if dist and kind != "Siłownia" else []
    cals = round((kcal_per * dist * 1000) if kcal_per else dur * 7.5, 0)
    return {
        "type": kind,
        "start": iso(start),
        "duration_min": dur,
        "distance_km": dist,
        "avg_hr": avg_hr + random.randint(-6, 6),
        "max_hr": max_hr + random.randint(-6, 6),
        "calories": cals,
        "pace_min_km": pace,
        "elevation_gain_m": elev,
        "route": route,
    }


# ---------------------------------------------------------------------------
# Serie tętna 24/7 (co 30 min = 48 punktów) — tylko dla dziś (oszczędność miejsca)
# ---------------------------------------------------------------------------

def gen_hr_series(rhr: float, has_workout: bool) -> list[dict]:
    series = []
    base_day = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(48):
        hour = i / 2
        # noc niskie, dzień wyższe, pik treningowy po południu
        if hour < 6.5:
            v = rhr + random.uniform(-2, 4)
        elif 17 <= hour <= 18.5 and has_workout:
            v = rhr + random.uniform(55, 95)
        else:
            v = rhr + 14 + math.sin(hour / 24 * math.tau) * 10 + random.uniform(-6, 10)
        series.append({"t": iso(base_day + timedelta(minutes=i * 30)), "bpm": round(clamp(v, 42, 185))})
    return series


# ---------------------------------------------------------------------------
# Pojedynczy dzień
# ---------------------------------------------------------------------------

def gen_day(day_index: int, date: datetime) -> dict:
    is_weekend = date.weekday() >= 5
    is_today = day_index == 29
    t = day_index / 29.0
    rough = 18 <= day_index <= 21  # "gorszy tydzień"

    # --- Sen ---
    base_sleep = 7.4 if not is_weekend else 7.9
    sleep_h = base_sleep + (-1.1 if rough else 0) + random.uniform(-0.5, 0.5)
    if day_index in (27, 28):
        sleep_h = random.uniform(5.2, 5.8)
    if is_today:
        sleep_h = random.uniform(7.7, 8.1)
    sleep_h = clamp(sleep_h, 4.3, 9.2)
    total_min = round(sleep_h * 60)

    deep = round(total_min * random.uniform(0.15, 0.21))
    rem = round(total_min * random.uniform(0.19, 0.25))
    awake = round(total_min * random.uniform(0.03, 0.08))
    light = total_min - deep - rem - awake

    bed_hour = 23 + (1.2 if is_weekend else 0)
    bed_jitter = random.uniform(-0.6, 0.9) + (0.5 if rough else 0)
    sleep_start = date.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1) + timedelta(hours=bed_hour + bed_jitter)
    sleep_end = sleep_start + timedelta(minutes=total_min)

    # Sleep Score (0-100) — "z urządzenia"
    sleep_score = round(clamp(
        50 + (sleep_h - 6) * 9 + (deep + rem) / total_min * 60 - awake / total_min * 40 + random.uniform(-4, 4),
        30, 98))

    # --- Tętno ---
    rhr = 54 + (4.5 if rough else 0) + math.sin(t * 6) * 1.5 + random.uniform(-1.5, 1.5)
    if is_today:
        rhr -= 1
    rhr = round(clamp(rhr, 48, 68), 1)

    hrv = 58 + t * 4 - (12 if rough else 0) + math.cos(t * 5) * 3 + random.uniform(-3, 3)
    if is_today:
        hrv += 4
    hrv = round(clamp(hrv, 28, 82), 1)

    # --- Aktywność ---
    steps = random.randint(6500, 11500) if not is_weekend else random.randint(3500, 14000)
    if day_index in (20, 26):
        steps = random.randint(2200, 4200)
    distance_km = round(steps * 0.00072 * random.uniform(0.95, 1.08), 2)
    calories = round(1750 + steps * 0.045 + random.uniform(-80, 120), 0)
    azm = round(clamp(steps / 350 + random.uniform(-8, 12), 0, 90))   # Active Zone Minutes
    active_minutes = round(azm * 1.6 + random.uniform(5, 25))
    swim_strokes = 0  # opaska wykrywa, ale Franek raczej nie pływa w demo

    # Strefy tętna (minuty)
    hr_zones = {
        "fat_burn": round(azm * 0.6 + random.uniform(10, 30)),
        "cardio": round(azm * 0.5 + random.uniform(2, 15)),
        "peak": round(max(0, azm * 0.15 + random.uniform(-3, 6))),
    }

    # --- Fizjologia ---
    spo2 = round(clamp(96 + random.uniform(-1.5, 2), 90, 100), 1)
    respiration = round(clamp(14.5 + (1.5 if rough else 0) + random.uniform(-1, 1.2), 11, 20), 1)
    skin_temp = round((0.6 if rough else 0) + random.uniform(-0.4, 0.4), 1)  # odchylenie °C
    cardio_load = round(clamp(azm * 1.8 + (steps / 500) + random.uniform(-10, 20), 5, 220))

    # --- Daily Readiness Score (0-100) — "z urządzenia" ---
    readiness_raw = (sleep_score * 0.4 + clamp((hrv - 40) * 1.5, 0, 40) +
                     clamp((60 - rhr) * 1.5, 0, 25) - (skin_temp * 10) + random.uniform(-3, 3))
    readiness_score = round(clamp(readiness_raw, 15, 99))
    if readiness_score >= 80:
        readiness_label = "Wysoka"
    elif readiness_score >= 60:
        readiness_label = "Dobra"
    elif readiness_score >= 40:
        readiness_label = "Umiarkowana"
    else:
        readiness_label = "Niska"

    # --- Treningi ---
    workouts = []
    if not rough and random.random() < (0.55 if not is_weekend else 0.75):
        kind = random.choice(["Bieg", "Rower", "Spacer", "Rower", "Siłownia"])
        workouts.append(gen_workout(date, kind))
    if is_today:
        workouts = [gen_workout(date, "Rower")]

    fetched = date.replace(hour=6, minute=55, second=0, microsecond=0)

    entry = {
        "fetched_at": iso(fetched),
        "period_start": iso(date - timedelta(days=1)),
        "period_end": iso(date),

        "steps": steps,
        "distance_km": distance_km,
        "calories_kcal": calories,
        "active_zone_minutes": azm,
        "active_minutes": active_minutes,
        "swim_strokes": swim_strokes,

        "heart_rate_bpm": {
            "avg": round(72 + (steps - 8000) / 1000 * 1.5 + random.uniform(-3, 3), 1),
            "min": round(rhr - random.uniform(2, 5), 1),
            "max": round(160 + random.uniform(-15, 20), 1),
        },
        "resting_hr_bpm": rhr,
        "hrv_rmssd": hrv,
        "hr_zones_minutes": hr_zones,
        "afib_status": "Brak nieprawidłowości",

        "spo2_pct": spo2,
        "respiration_rate": respiration,
        "skin_temp_variation_c": skin_temp,
        "cardio_load": cardio_load,

        "daily_readiness": {"score": readiness_score, "label": readiness_label},

        "sleep": {
            "total_minutes": total_min,
            "sleep_start": iso(sleep_start),
            "sleep_end": iso(sleep_end),
            "sleep_score": sleep_score,
            "stages_minutes": {"deep": deep, "rem": rem, "light": light, "awake": awake},
        },

        "workouts": workouts,
        "_demo": True,
    }

    # Serię 24/7 dołączamy tylko dla dziś (rozmiar pliku)
    if is_today:
        entry["hr_series"] = gen_hr_series(rhr, has_workout=bool(workouts))

    return entry


def generate(days: int = 30) -> list[dict]:
    today = datetime.now(TZ).replace(hour=7, minute=0, second=0, microsecond=0)
    return [gen_day(i, today - timedelta(days=(days - 1 - i))) for i in range(days)]


def main() -> None:
    history = generate(30)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    size = OUT.stat().st_size
    print(f"[demo] Zapisano {len(history)} dni ({size//1024} KB) -> {OUT}")


if __name__ == "__main__":
    main()
