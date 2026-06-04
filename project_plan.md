# Projekt: BioAI-Pulse (Integracja Fitbit Air z Claude AI)

## 1. Cel Projektu
Stworzenie automatycznego systemu analizy danych zdrowotnych i biometrycznych. System ma pobierać dane z opaski **Fitbit Air** (poprzez oficjalne API Google/Fitbit), przetwarzać je lokalnie do ustrukturyzowanego formatu JSON/CSV, a następnie wykorzystywać **Claude** jako osobistego analityka zdrowia i trenera (Adaptive Health Coach).

## 2. Architektura i Przepływ Danych (Data Pipeline)
1. **Sensor:** Fitbit Air (zbieranie danych: tętno, sen, HRV, aktywność).
2. **Synchronizacja:** Opaska -> Bluetooth -> iPhone (Aplikacja Fitbit) -> Chmura Google.
3. **Pobieranie (Ingestion):** Skrypt Python autoryzuje się przez OAuth 2.0 i pobiera dane z Google Health API / Fitbit API.
4. **Baza lokalna:** Dane są czyszczone i zapisywane w formacie JSON lub lokalnej bazie SQLite (`health_data.db`).
5. **Analiza (Claude Code):** Claude analizuje trendy, generuje codzienne raporty regeneracji i podsuwa spersonalizowane porady.

---

## 3. Ekosystem Technologiczny
* **Hardware:** Fitbit Air (urządzenie bezekranowe).
* **Środowisko deweloperskie:** Claude Code (interfejs terminalowy do zarządzania projektem i pisania kodu).
* **Język programowania:** Python 3.10+ (biblioteki: `requests`, `pandas`, `sqlite3`, `oauthlib`).
* **Źródło danych:** Google Health API / Fitbit Web API.
* **Format danych docelowych:** JSON / DataFrame (czysty, zanonimizowany).

---

## 4. Kamienie Milowe i Fazy Projektu

### Faza 1: Konfiguracja API i Autoryzacja (OAuth 2.0)
* Założenie konta deweloperskiego w Google Cloud / Fitbit Developer Portal.
* Konfiguracja aplikacji, uzyskanie `Client ID` i `Client Secret`.
* Napisanie skryptu `auth.py` obsługującego proces uwierzytelnienia i odświeżania tokenów (`refresh_token`).

### Faza 2: Skrypt Pobierający Dane (`fetch_data.py`)
* Implementacja zapytań do API o konkretne punkty danych z ostatnich 24h:
  * Jakość i fazy snu.
  * Zmienność tętna (HRV - Heart Rate Variability).
  * Tętno spoczynkowe (Resting Heart Rate).
  * Aktywność fizyczna (kroki, spalone kalorie).
* Zapisywanie danych do lokalnego pliku `data/daily_metrics.json`.

### Faza 3: Silnik Analizy AI (`analyzer.py` / Prompt Engineering)
* Stworzenie szablonu systemowego dla Claude (`prompts/health_coach.md`).
* Integracja skryptu z Claude Code tak, aby model potrafił interpretować lokalne pliki JSON.
* Generowanie raportu porannego (Morning Readiness Report) oraz wieczornego podsumowania.

### Faza 4: Automatyzacja
* Przygotowanie skryptu uruchamiającego cały proces jednym poleceniem w terminalu lub poprzez lokalny harmonogram zadań (np. cron).

---

## 5. Instrukcje dla Claude Code
Jako agent AI zarządzający tym projektem, Twoim zadaniem jest:
1. Pomoc w napisaniu czystego, modułowego kodu w Pythonie do obsługi API.
2. Pilnowanie bezpieczeństwa (przechowywanie kluczy API w pliku `.env`, który jest w `.gitignore`).
3. Zaprojektowanie struktury bazy danych/JSON-a w taki sposób, aby była najbardziej optymalna do analizy kontekstowej przez LLM.
4. Unikanie skomplikowanych zależności zewnętrznych – system ma być lekki i uruchamiany lokalnie.