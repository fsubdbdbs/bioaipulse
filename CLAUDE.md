# BioAI-Pulse — Kontekst dla Claude Code

## Co to jest

Automatyczny pipeline zdrowotny: Fitbit Air → Google Fitness API → AI raporty.
Właściciel projektu: Franek. Mów do niego po imieniu.

## Serwer

- VPS Ubuntu 24.04, IP: 31.70.72.157
- Projekt siedzi w: `/root/bioaipulse/`
- Domena SSL: `franek-health.duckdns.org` (Let's Encrypt, auto-renewal)
- Połączenie: `ssh root@31.70.72.157`

## Stan projektu (czerwiec 2026)

Wszystkie 4 fazy ukończone. Pipeline działa end-to-end.
Brakuje tylko opaski Fitbit Air — Franek jeszcze jej nie kupił.
Dane z API zwracają `null` / `0` bo nie ma urządzenia — to normalne.

## Pliki i ich rola

| Plik | Rola |
|---|---|
| `auth.py` | OAuth 2.0 Google — autoryzacja, zapis tokenów, auto-refresh |
| `fetch_data.py` | Pobiera dane z Google Fitness API (sen, tętno, HRV, kroki, kalorie) |
| `analyzer.py` | Wysyła dane do Groq API (Llama 3.3 70B), generuje raporty |
| `run.sh` | Uruchamia fetch + analyze jednym poleceniem |
| `prompts/health_coach.md` | System prompt dla AI — persona "Pulse", język PL |
| `data/daily_metrics.json` | Historia danych (rolling 30 dni) |
| `data/reports/` | Wygenerowane raporty tekstowe |
| `tokens/google_tokens.json` | Tokeny OAuth (nie ruszać ręcznie) |
| `logs/` | Logi z crona |
| `api/index.py` | Backend Flask (Vercel serverless) — API: login, dane, czat AI, push, przypominajki |
| `app/analytics.py` | Silnik analiz: readiness (z opaski), baseline, insighty, plany pod cel |
| `app/demo_data.py` | Generator danych demo (30 dni, WSZYSTKIE pola opaski) |
| `app/generate_icons.py` | Generator ikon PWA (czysty Python) |
| `app/generate_vapid.py` | Generator kluczy VAPID do powiadomień push |
| `public/` | Frontend PWA (index.html, app.js, styles.css, sw.js, manifest, icons) |
| `vercel.json` | Konfiguracja hostingu Vercel (routing static + funkcje api/) |
| `data/demo_metrics.json` | Dane demo (regenerowalne: `python3 app/demo_data.py`) |

## Zmienne środowiskowe (.env na VPS)

```
FITBIT_CLIENT_ID         # Google Cloud OAuth client ID
FITBIT_CLIENT_SECRET     # Google Cloud OAuth client secret
FITBIT_REDIRECT_URI      # https://franek-health.duckdns.org:8080/callback
SSL_CERTFILE             # /etc/letsencrypt/live/franek-health.duckdns.org/fullchain.pem
SSL_KEYFILE              # /etc/letsencrypt/live/franek-health.duckdns.org/privkey.pem
GROQ_API_KEY             # Groq API (darmowy, Llama 3.3 70B)
```

## Cron na VPS

```
0 7  * * *  bash /root/bioaipulse/run.sh morning   # raport poranny
0 22 * * *  bash /root/bioaipulse/run.sh evening   # raport wieczorny
```

## Decyzje techniczne i dlaczego

- **Google Fitness API zamiast Fitbit Web API** — Fitbit zamknął rejestrację nowych aplikacji w 2026, wymusza Google Health API
- **Groq zamiast Gemini/Claude API** — Google wymaga karty płatniczej nawet dla free tier; Groq jest w pełni darmowy bez karty
- **DuckDNS + Let's Encrypt** — Google OAuth wymaga HTTPS z prawdziwą domeną, raw IP nie przechodzi
- **Tokeny w `tokens/`** — poza `.gitignore`, nigdy nie commitować
- **Rolling 30 dni w JSON** — wystarczy dla kontekstu AI, nie wymaga SQLite

## Znane problemy / rzeczy do pamiętania

- Token Google ważny ~6 miesięcy — jak fetch_data.py przestanie działać, odpalić `python3 auth.py` na VPS
- HRV (RMSSD) może zwracać `null` nawet z opaską — zależy od modelu (wymaga Fitbit Sense lub Charge 5+)
- Port 8080 potrzebny tylko podczas pierwszej autoryzacji OAuth — potem można zamknąć
- `sed -i` na VPS modyfikuje pliki bezpośrednio — przy aktualizacjach kodu używać `scp` z lokalnej maszyny

## Aplikacja PWA (dashboard na iPhone) — hostowana na Vercel

Apka to PWA instalowana przez Safari („Do ekranu początkowego"). Hosting: **Vercel + GitHub** (darmowy, auto-HTTPS). Bez App Store, bez konta Apple Developer.

**5 zakładek:**
- **Dziś** — W PEŁNI KONFIGUROWALNY ekran (tryb „✎ Dostosuj"): widgety dodawanie/usuwanie/kolejność, wybór metryki głównego kółka (readiness/sleep score/kroki/AZM/HRV/cardio load), żywa porada coacha. Układ zapisany w localStorage.
- **Trendy** — przełączane wykresy 14 dni (readiness, sleep score, sen, RHR, HRV, kroki, SpO2, obciążenie).
- **Treningi** — lista treningów + szczegóły z mapą trasy (Leaflet), tempo, przewyższenie, tętno.
- **Coach AI** — PRAWDZIWY czat (Groq/Llama 3.3) na bieżąco z danymi + 6 celów + 3 plany + raport.
- **Profil** — przypominajki (push), linie bazowe, instalacja, eksport.

**Dane z opaski (wszystkie):** kroki, dystans, kalorie, Active Zone Minutes, czas ruchu, tętno 24/7, RHR, strefy tętna, HRV, Afib, sen (czas/fazy/Sleep Score/regularność), SpO2, oddech, temp. skóry, Cardio Load, Daily Readiness, treningi (SmartTrack + manualne), trasy GPS, tempo, przewyższenie. **Sleep Score i Daily Readiness bierzemy wprost z opaski — nie przeliczamy.**

**Źródło danych:** `DEMO_MODE=1` lub brak prawdziwych → `data/demo_metrics.json`. Inaczej → `data/daily_metrics.json`.

### Wdrożenie na Vercel
1. Wrzuć projekt na GitHub (`git init`, commit, push).
2. Na vercel.com: „New Project" → import repo. Vercel sam wykryje `vercel.json`.
3. W ustawieniach projektu → Environment Variables dodaj: `APP_PIN`, `APP_SECRET`, `GROQ_API_KEY` (czat AI), `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`, `CRON_SECRET`. (Klucze VAPID: `python3 app/generate_vapid.py`.)
4. Powiadomienia push wymagają trwałego storage między wywołaniami → włącz **Vercel KV** (zakładka Storage, darmowy tier). Ustawia automatycznie `KV_REST_API_URL` i `KV_REST_API_TOKEN`.
5. Deploy. Otwórz adres `*.vercel.app` w Safari → „Do ekranu początkowego". Push działa dopiero z apki zainstalowanej na ekranie głównym.

### Przypominajki push (harmonogram)
Darmowy cron Vercela jest ograniczony, więc wyzwalamy je z crona VPS (działa co minutę):
```
*/5 * * * *  curl -s "https://TWOJA-APKA.vercel.app/api/cron/reminders?key=CRON_SECRET" >/dev/null
```

**Test lokalny:** `python3 api/index.py` → `http://127.0.0.1:8000` (PIN: 2137). Bez `GROQ_API_KEY` czat działa w trybie uproszczonym.

## Jak testować po zakupie opaski

1. Sparuj opaskę z aplikacją Fitbit na telefonie
2. Włącz synchronizację z Google Fit w ustawieniach Fitbit
3. Poczekaj ~15 minut na pierwszą synchronizację
4. Na VPS: `cd /root/bioaipulse && python3 fetch_data.py`
5. Sprawdź czy dane są inne niż `null`
6. `python3 analyzer.py --mode morning` — pierwszy prawdziwy raport
