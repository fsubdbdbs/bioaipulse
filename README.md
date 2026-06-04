# BioAI-Pulse

Automatyczny system analizy danych zdrowotnych z opaski Fitbit Air. Pipeline pobiera dane biometryczne przez Google Fitness API, a następnie generuje codzienne raporty zdrowotne przy użyciu AI.

---

## Cel projektu

Stworzenie osobistego analityka zdrowia działającego w tle — bez żadnej ręcznej obsługi. System codziennie o 7:00 i 22:00 pobiera dane z opaski i generuje raport gotowości na dany dzień oraz wieczorne podsumowanie aktywności.

---

## Architektura

```
Fitbit Air → Bluetooth → Aplikacja Fitbit (iPhone) → Google Fit Cloud
                                                              ↓
                                                   fetch_data.py (OAuth 2.0)
                                                              ↓
                                                  data/daily_metrics.json
                                                              ↓
                                                       analyzer.py
                                                              ↓
                                              data/reports/YYYY-MM-DD_morning.txt
```

---

## Stack technologiczny

| Warstwa | Technologia |
|---|---|
| Hardware | Fitbit Air |
| Serwer | VPS Ubuntu 24.04 (31.70.72.157) |
| Język | Python 3.12 |
| Autoryzacja | OAuth 2.0 — Google Cloud |
| API danych | Google Fitness API |
| AI / Raporty | Llama 3.3 70B via Groq API (darmowe) |
| Automatyzacja | cron (7:00 i 22:00 UTC) |
| Domena SSL | franek-health.duckdns.org (Let's Encrypt) |

---

## Struktura plików

```
bioaipulse/
├── auth.py              # OAuth 2.0 — autoryzacja i refresh tokenów
├── fetch_data.py        # Pobieranie danych z Google Fitness API
├── analyzer.py          # Silnik AI — generowanie raportów
├── run.sh               # Skrypt uruchamiający cały pipeline
├── .env                 # Klucze API (nie commitować)
├── .env.example         # Szablon zmiennych środowiskowych
├── .gitignore
├── data/
│   ├── daily_metrics.json   # Historia danych (ostatnie 30 dni)
│   └── reports/             # Wygenerowane raporty tekstowe
├── prompts/
│   └── health_coach.md      # Prompt systemowy dla AI
├── tokens/
│   └── google_tokens.json   # Tokeny OAuth (nie commitować)
└── logs/
    ├── fetch.log
    └── analyzer.log
```

---

## Zbierane dane

- Kroki dzienne
- Spalone kalorie
- Tętno (avg / min / max)
- Tętno spoczynkowe (RHR)
- Zmienność tętna (HRV RMSSD) — wymaga Fitbit Sense/Charge 5+
- Sen (łączny czas, fazy: deep / REM / light / awake)

---

## Status faz

| Faza | Opis | Status |
|---|---|---|
| Faza 1 | OAuth 2.0 — autoryzacja Google, tokeny | ✅ Gotowe |
| Faza 2 | fetch_data.py — pobieranie danych z API | ✅ Gotowe |
| Faza 3 | analyzer.py — silnik AI, raporty | ✅ Gotowe |
| Faza 4 | Automatyzacja — cron VPS | ✅ Gotowe |
| Oczekuje | Zakup opaski Fitbit Air | ⏳ W toku |

---

## Aplikacja mobilna (PWA) — hosting na Vercel

Dashboard na iPhone instalowany przez Safari („Udostępnij" → „Do ekranu początkowego") — bez App Store i bez konta Apple Developer. Chroniony PIN-em. Hosting: **Vercel + GitHub** (darmowy, auto-HTTPS).

| Zakładka | Co pokazuje |
|---|---|
| **Dziś** | W pełni konfigurowalny ekran (widgety): główne kółko z wybieraną metryką, pierścienie aktywności, sen, parametry, strefy tętna, tętno 24/7, żywa porada coacha |
| **Trendy** | Przełączane wykresy 14 dni: readiness, sleep score, sen, RHR, HRV, kroki, SpO2, obciążenie |
| **Treningi** | Lista treningów + szczegóły z mapą trasy GPS, tempem, przewyższeniem |
| **Coach AI** | Prawdziwy czat AI (Groq) na bieżąco z danymi + 6 celów + 3 plany dnia + raport |
| **Profil** | Przypominajki push (woda, ruch, sen), linie bazowe, instalacja, eksport |

Wszystkie dane z opaski (steps, dystans, AZM, tętno 24/7, strefy, HRV, Afib, sen + Sleep Score, SpO2, oddech, temp. skóry, Cardio Load, Daily Readiness, treningi, GPS). Sleep Score i Daily Readiness brane wprost z urządzenia.

```bash
pip install -r requirements.txt
python3 app/demo_data.py          # dane demo (zanim opaska dotrze)
python3 api/index.py              # test lokalny → http://127.0.0.1:8000  (PIN: 2137)
```

Wdrożenie na Vercel (env vars, Vercel KV, cron push) — patrz `CLAUDE.md`.

---

## Uruchomienie ręczne (pipeline danych)

```bash
cd /root/bioaipulse

# Jednorazowa autoryzacja (tylko za pierwszym razem)
python3 auth.py

# Pobranie danych
python3 fetch_data.py

# Raport poranny
python3 analyzer.py --mode morning

# Raport wieczorny
python3 analyzer.py --mode evening

# Cały pipeline jednym poleceniem
bash run.sh morning
```

---

## Cron (automatyczne uruchomienia)

```
0 7  * * *  bash /root/bioaipulse/run.sh morning
0 22 * * *  bash /root/bioaipulse/run.sh evening
```

---

## Następne kroki po zakupie opaski

1. Zainstaluj aplikację Fitbit na telefonie
2. Sparuj opaskę przez Bluetooth
3. W ustawieniach Fitbit włącz synchronizację z Google Fit
4. Odpal `bash run.sh morning` — pierwsze dane pojawią się w ciągu kilku minut po synchronizacji
5. Sprawdź `data/reports/` — tam lądują wygenerowane raporty

---

## Bezpieczeństwo

Klucze API przechowywane w pliku `.env` (poza repozytorium). Tokeny OAuth w `tokens/` (poza repozytorium). SSL na domenie franek-health.duckdns.org z certyfikatem Let's Encrypt (auto-renewal).
