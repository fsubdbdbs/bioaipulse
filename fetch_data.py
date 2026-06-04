"""
fetch_data.py — Google Fitness API Data Fetcher
BioAI-Pulse Project

Pobiera dane z ostatnich 24h:
  - Kroki
  - Spalone kalorie
  - Tętno (avg / min / max)
  - Tętno spoczynkowe (RHR)
  - Zmienność tętna (HRV)
  - Sen (fazy, łączny czas)

Zapisuje wynik do: data/daily_metrics.json

Usage:
  python3 fetch_data.py
  python3 fetch_data.py --days 7    # ostatnie 7 dni
"""

import json
import time
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

from auth import get_headers

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

FITNESS_API   = "https://www.googleapis.com/fitness/v1/users/me"
DATA_PATH     = Path("data/daily_metrics.json")

SLEEP_STAGES  = {1: "awake", 2: "sleep", 3: "out_of_bed", 4: "light", 5: "deep", 6: "rem"}

# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def now_ms() -> int:
    return int(time.time() * 1000)

def ms_ago(days: int) -> int:
    return int((time.time() - days * 86400) * 1000)

def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()

# ---------------------------------------------------------------------------
# Core: aggregate endpoint
# ---------------------------------------------------------------------------

def aggregate(headers: dict, data_type: str, start_ms: int, end_ms: int,
              bucket_ms: int = None) -> dict:
    """
    POST /dataset:aggregate — fetch bucketed data for a given data type.
    If bucket_ms is None, returns one bucket for the whole period.
    """
    body = {
        "aggregateBy": [{"dataTypeName": data_type}],
        "startTimeMillis": start_ms,
        "endTimeMillis":   end_ms,
    }
    if bucket_ms:
        body["bucketByTime"] = {"durationMillis": bucket_ms}
    else:
        body["bucketByTime"] = {"durationMillis": end_ms - start_ms}

    r = requests.post(
        f"{FITNESS_API}/dataset:aggregate",
        headers={**headers, "Content-Type": "application/json"},
        json=body,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def extract_fp_value(bucket: dict, field: str = "fpVal") -> float | None:
    """Pull a single float value from a bucket's first dataset point."""
    for ds in bucket.get("dataset", []):
        for point in ds.get("point", []):
            for val in point.get("value", []):
                v = val.get(field) or val.get("intVal")
                if v is not None:
                    return float(v)
    return None


def extract_int_value(bucket: dict) -> int | None:
    for ds in bucket.get("dataset", []):
        for point in ds.get("point", []):
            for val in point.get("value", []):
                v = val.get("intVal") or val.get("fpVal")
                if v is not None:
                    return int(v)
    return None

# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_steps(headers: dict, start_ms: int, end_ms: int) -> int:
    data   = aggregate(headers, "com.google.step_count.delta", start_ms, end_ms)
    total  = 0
    for bucket in data.get("bucket", []):
        v = extract_int_value(bucket)
        if v:
            total += v
    return total


def fetch_calories(headers: dict, start_ms: int, end_ms: int) -> float:
    data  = aggregate(headers, "com.google.calories.expended", start_ms, end_ms)
    total = 0.0
    for bucket in data.get("bucket", []):
        v = extract_fp_value(bucket)
        if v:
            total += v
    return round(total, 1)


def fetch_heart_rate(headers: dict, start_ms: int, end_ms: int) -> dict:
    """Returns avg / min / max heart rate over the period."""
    data    = aggregate(headers, "com.google.heart_rate.bpm", start_ms, end_ms)
    values  = []

    for bucket in data.get("bucket", []):
        for ds in bucket.get("dataset", []):
            for point in ds.get("point", []):
                vals = point.get("value", [])
                # Google returns [avg, max, min] in that order
                if len(vals) >= 3:
                    avg = vals[0].get("fpVal")
                    if avg:
                        values.append(avg)

    if not values:
        return {"avg": None, "min": None, "max": None}

    return {
        "avg": round(sum(values) / len(values), 1),
        "min": round(min(values), 1),
        "max": round(max(values), 1),
    }


def fetch_resting_heart_rate(headers: dict, start_ms: int, end_ms: int) -> float | None:
    # Try multiple data types — availability depends on device
    for dtype in [
        "com.google.heart_rate.bpm",   # fallback: use min HR as proxy for RHR
    ]:
        try:
            data = aggregate(headers, dtype, start_ms, end_ms)
            mins = []
            for bucket in data.get("bucket", []):
                for ds in bucket.get("dataset", []):
                    for point in ds.get("point", []):
                        vals = point.get("value", [])
                        if len(vals) >= 3:
                            min_val = vals[2].get("fpVal")
                            if min_val:
                                mins.append(min_val)
            if mins:
                return round(min(mins), 1)
        except requests.HTTPError:
            continue
    return None


def fetch_hrv(headers: dict, start_ms: int, end_ms: int) -> float | None:
    """HRV RMSSD — dostępne tylko na wybranych urządzeniach (np. Fitbit Sense/Charge 5+)."""
    try:
        data = aggregate(
            headers,
            "com.google.heart_rate.variability.rmssd.wrist",
            start_ms,
            end_ms,
        )
        for bucket in data.get("bucket", []):
            v = extract_fp_value(bucket)
            if v:
                return round(v, 2)
    except requests.HTTPError:
        return None   # device doesn't support HRV or data type unavailable
    return None


def fetch_sleep(headers: dict, start_ms: int, end_ms: int) -> dict:
    """
    Pobiera sesje snu przez /sessions endpoint.
    Zwraca: łączny czas snu, fazy (light/deep/rem/awake), godzina zaśnięcia/przebudzenia.
    """
    r = requests.get(
        f"{FITNESS_API}/sessions",
        headers=headers,
        params={
            "startTime":    ms_to_iso(start_ms),
            "endTime":      ms_to_iso(end_ms),
            "activityType": 72,   # 72 = sleep
        },
        timeout=15,
    )
    r.raise_for_status()
    sessions = r.json().get("session", [])

    if not sessions:
        return {
            "total_minutes": None,
            "sleep_start":   None,
            "sleep_end":     None,
            "stages":        {},
        }

    # Pick longest sleep session (główna noc)
    main = max(sessions, key=lambda s: int(s["endTimeMillis"]) - int(s["startTimeMillis"]))
    start = int(main["startTimeMillis"])
    end   = int(main["endTimeMillis"])
    total_minutes = round((end - start) / 60000)

    # Fetch stage breakdown
    stages: dict[str, int] = {}
    try:
        stage_data = aggregate(
            headers,
            "com.google.sleep.segment",
            start,
            end,
        )
        for bucket in stage_data.get("bucket", []):
            for ds in bucket.get("dataset", []):
                for point in ds.get("point", []):
                    stage_int = point.get("value", [{}])[0].get("intVal")
                    stage_name = SLEEP_STAGES.get(stage_int, "unknown")
                    duration_ms = int(point["endTimeNanos"]) // 1_000_000 - \
                                  int(point["startTimeNanos"]) // 1_000_000
                    stages[stage_name] = stages.get(stage_name, 0) + round(duration_ms / 60000)
    except Exception:
        pass   # stage data not critical — total time is enough

    return {
        "total_minutes": total_minutes,
        "sleep_start":   ms_to_iso(start),
        "sleep_end":     ms_to_iso(end),
        "stages_minutes": stages,
    }

# ---------------------------------------------------------------------------
# Main fetch function
# ---------------------------------------------------------------------------

def fetch_all(days: int = 1) -> dict:
    headers  = get_headers()
    end_ms   = now_ms()
    start_ms = ms_ago(days)

    print(f"[fetch] Fetching data for last {days} day(s)...")
    print(f"        From: {ms_to_iso(start_ms)}")
    print(f"        To:   {ms_to_iso(end_ms)}\n")

    metrics = {
        "fetched_at":  ms_to_iso(now_ms()),
        "period_days": days,
        "period_start": ms_to_iso(start_ms),
        "period_end":   ms_to_iso(end_ms),
    }

    # Steps
    print("[fetch] Steps...")
    metrics["steps"] = fetch_steps(headers, start_ms, end_ms)

    # Calories
    print("[fetch] Calories...")
    metrics["calories_kcal"] = fetch_calories(headers, start_ms, end_ms)

    # Heart rate
    print("[fetch] Heart rate...")
    metrics["heart_rate_bpm"] = fetch_heart_rate(headers, start_ms, end_ms)

    # Resting heart rate
    print("[fetch] Resting heart rate...")
    metrics["resting_hr_bpm"] = fetch_resting_heart_rate(headers, start_ms, end_ms)

    # HRV
    print("[fetch] HRV...")
    metrics["hrv_rmssd"] = fetch_hrv(headers, start_ms, end_ms)

    # Sleep
    print("[fetch] Sleep...")
    metrics["sleep"] = fetch_sleep(headers, start_ms, end_ms)

    return metrics

# ---------------------------------------------------------------------------
# Save & entry point
# ---------------------------------------------------------------------------

def save(metrics: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Append to history if file exists
    history = []
    if DATA_PATH.exists():
        with open(DATA_PATH) as f:
            existing = json.load(f)
            if isinstance(existing, list):
                history = existing
            else:
                history = [existing]

    history.append(metrics)

    # Keep last 30 days
    history = history[-30:]

    with open(DATA_PATH, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    print(f"\n[fetch] Saved → {DATA_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Google Fitness data")
    parser.add_argument("--days", type=int, default=1, help="How many days back to fetch (default: 1)")
    args = parser.parse_args()

    metrics = fetch_all(days=args.days)

    print("\n--- Results ---")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))

    save(metrics)
