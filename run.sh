#!/bin/bash
# run.sh — BioAI-Pulse runner
# Uruchamiany przez cron. Pobiera dane i generuje raport.
# Użycie: bash run.sh morning | bash run.sh evening

MODE=${1:-morning}
DIR=/root/bioaipulse

cd "$DIR" || exit 1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Startuje pipeline — tryb: $MODE"

python3 fetch_data.py >> logs/fetch.log 2>&1
python3 analyzer.py --mode "$MODE" >> logs/analyzer.log 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Gotowe."
