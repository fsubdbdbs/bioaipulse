"""
analyzer.py — AI Health Analysis Engine
BioAI-Pulse Project

Czyta dane z data/daily_metrics.json, wysyła do Groq API (Llama 3.3 70B)
i generuje Morning Readiness Report lub Evening Summary.

Usage:
  python3 analyzer.py              # Morning report (domyślnie)
  python3 analyzer.py --mode evening   # Evening summary
  python3 analyzer.py --days 3         # Ostatnie 3 dni kontekstu
"""

import os
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

METRICS_PATH = Path("data/daily_metrics.json")
PROMPT_PATH  = Path("prompts/health_coach.md")
REPORTS_PATH = Path("data/reports")

GROQ_KEY     = os.getenv("GROQ_API_KEY")
MODEL        = "llama-3.3-70b-versatile"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_metrics(days: int = 3) -> list[dict]:
    """Load last N days of metrics from JSON."""
    if not METRICS_PATH.exists():
        raise FileNotFoundError(
            f"Brak pliku {METRICS_PATH}. Uruchom najpierw: python3 fetch_data.py"
        )
    with open(METRICS_PATH) as f:
        history = json.load(f)

    if isinstance(history, dict):
        history = [history]

    return history[-days:]


def load_system_prompt() -> str:
    with open(PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def format_metrics_for_prompt(metrics_history: list[dict], mode: str) -> str:
    """Format metrics into a readable block for the LLM."""
    lines = [f"# Dane biometryczne Franka — {mode.upper()}\n"]

    for entry in metrics_history:
        date = entry.get("fetched_at", "nieznana data")[:10]
        lines.append(f"## {date}")

        # Steps & calories
        steps    = entry.get("steps")
        calories = entry.get("calories_kcal")
        lines.append(f"- Kroki: {steps if steps is not None else 'brak danych'}")
        lines.append(f"- Kalorie: {calories if calories is not None else 'brak danych'} kcal")

        # Heart rate
        hr = entry.get("heart_rate_bpm", {})
        lines.append(f"- Tętno avg: {hr.get('avg') or 'brak'} bpm | "
                     f"min: {hr.get('min') or 'brak'} | max: {hr.get('max') or 'brak'}")

        # RHR
        rhr = entry.get("resting_hr_bpm")
        lines.append(f"- Tętno spoczynkowe: {rhr if rhr is not None else 'brak danych'} bpm")

        # HRV
        hrv = entry.get("hrv_rmssd")
        lines.append(f"- HRV (RMSSD): {hrv if hrv is not None else 'brak danych'} ms")

        # Sleep
        sleep = entry.get("sleep", {})
        total = sleep.get("total_minutes")
        if total:
            h, m = divmod(total, 60)
            lines.append(f"- Sen: {h}h {m}min")
            lines.append(f"  Zaśnięcie: {sleep.get('sleep_start', 'brak')[:16].replace('T', ' ')}")
            lines.append(f"  Przebudzenie: {sleep.get('sleep_end', 'brak')[:16].replace('T', ' ')}")
            stages = sleep.get("stages_minutes", {})
            if stages:
                lines.append(f"  Fazy: deep={stages.get('deep', 0)}min | "
                              f"rem={stages.get('rem', 0)}min | "
                              f"light={stages.get('light', 0)}min | "
                              f"awake={stages.get('awake', 0)}min")
        else:
            lines.append("- Sen: brak danych")

        lines.append("")

    return "\n".join(lines)


def generate_report(mode: str, metrics_text: str, system_prompt: str) -> str:
    """Call Groq API and return the report."""
    client = Groq(api_key=GROQ_KEY)

    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    hour  = datetime.now(timezone.utc).strftime("%H:%M")

    if mode == "morning":
        user_message = (
            f"Dzisiaj jest {today}, godzina {hour} UTC. "
            f"Wygeneruj Morning Readiness Report dla Franka na podstawie poniższych danych.\n\n"
            f"{metrics_text}"
        )
    else:
        user_message = (
            f"Dzisiaj jest {today}, godzina {hour} UTC. "
            f"Wygeneruj Evening Summary dla Franka na podstawie poniższych danych.\n\n"
            f"{metrics_text}"
        )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
        max_tokens=1024,
    )
    return response.choices[0].message.content


def save_report(report: str, mode: str) -> Path:
    REPORTS_PATH.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    filename  = REPORTS_PATH / f"{timestamp}_{mode}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(report)
    return filename


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BioAI-Pulse Analyzer")
    parser.add_argument(
        "--mode", choices=["morning", "evening"], default="morning",
        help="Typ raportu (domyślnie: morning)"
    )
    parser.add_argument(
        "--days", type=int, default=3,
        help="Ile dni historii wysłać do AI jako kontekst (domyślnie: 3)"
    )
    args = parser.parse_args()

    if not GROQ_KEY:
        raise EnvironmentError(
            "Brak GROQ_API_KEY w pliku .env\n"
            "Pobierz klucz ze: https://console.groq.com/keys"
        )

    print(f"[analyzer] Wczytywanie ostatnich {args.days} dni danych...")
    metrics_history = load_metrics(days=args.days)
    system_prompt   = load_system_prompt()
    metrics_text    = format_metrics_for_prompt(metrics_history, args.mode)

    print(f"[analyzer] Generowanie raportu ({args.mode}) przez Groq...")
    report = generate_report(args.mode, metrics_text, system_prompt)

    print("\n" + "=" * 50)
    print(report)
    print("=" * 50 + "\n")

    saved_path = save_report(report, args.mode)
    print(f"[analyzer] Raport zapisany → {saved_path}")
