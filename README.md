# Multi-Sensor Fusion: Radar (AWR2944) & BLE 

Tento projekt implementuje systém pro sledování objektů v reálném čase v testovacím poli 3x3 metry. Systém asynchronně kombinuje data ze dvou radarů **TI AWR2944** a dvou **u-blox BLE** kotev pro přesnou lokalizaci a identifikaci osob/tagů.

## Architektura systému

Projekt je postaven na moderním asynchronním zpracování (Python `asyncio`, `asyncpg`) a skládá se ze tří hlavních subsystémů běžících paralelně (`main.py`):

1. **Ingestion Engine (`ingestion.py`)**: Sběr dat přes UART ze senzorů, transformace souřadnic do globálního prostoru a dávkový asynchronní zápis surových dat do PostgreSQL.
2. **Fusion Engine (`fusion.py`)**: Algoritmus pro fúzi senzorů. Využívá shlukování **DBSCAN** pro radarová data a párování s BLE azimuty. Pohyb cílů je vyhlazován pomocí 2D **Kalmanova filtru** (`kalman_filter.py`).
3. **Vizualizační API (`app.py` + `index.html`)**: Webový server na platformě **FastAPI**. Přenáší zpracovaná data z databáze do webového prohlížeče v reálném čase pomocí **WebSockets**.

## Reálná struktura projektu

### Aktivní jádro aplikace
* `main.py` – Hlavní spouštěč celého systému (spravuje vlákna a asynchronní smyčky).
* `app.py` – Backend pro webové rozhraní a WebSocket komunikaci.
* `index.html` – Frontend vizualizace (Canvas) vykreslující objekty a senzory.
* `fusion.py` – Fúzní logika, přiřazování tagů a triangulace.
* `ingestion.py` – Sériová komunikace, parsování BLE zpráv (UUDF) a obsluha radarů.
* `db_handler.py` – Optimalizované databázové spojení a vytváření tabulek (`asyncpg`).
* `kalman_filter.py` – Matematický model pro predikci a korekci pozic objektů.

### Radarový subsystém (`/radar`)
* `radar_interface.py` – Třída pro připojení k sériovým portům radaru.
* `parser_mmw_demo.py` – Dekodér binárního TLV toku (Point Cloud) z radaru TI.
* `tdm/AWR294X_profile_... copy1.cfg` – Aktivní konfigurační profil radaru (TDM MIMO).

*(Pozn.: Složka `radar` obsahuje i starší testovací skripty jako `rad.py`, `radar_ui.py` a další `.cfg` profily, které slouží pouze pro offline testování a nejsou součástí produkčního běhu fúze).*

## Jak systém spustit

### 1. Prerekvizity a databáze
* Zprovozněný **PostgreSQL** server (přihlašovací údaje viz `db_handler.py`).
* Tabulky a indexy se vytvoří samy po spuštění aplikace.
* Python závislosti: `pip install fastapi uvicorn asyncpg pyserial numpy scikit-learn matplotlib`

### 2. Konfigurace portů
Před spuštěním ověřte COM porty v `ingestion.py` pro proměnné `BLE_CONFIGS` a `RADAR_CONFIGS`.

### 3. Spuštění
```bash
python main.py
```
### 4. Vizualizace
Po úspěšném startu všech 3 vláken otevřete v prohlížeči adresu: `http://127.0.0.1:8000`
