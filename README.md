# Four

Projekt pro sber, fuzi a vizualizaci dat z radaru a BLE kotev.

Datovy tok:

```text
radar/BLE senzory -> ingestion.py -> MQTT -> fusion.py -> MQTT -> app.py -> WebSocket -> index.html
```

## Struktura Projektu

```text
Four/
+- data/
|  \- optitrack/           # OptiTrack workbooky a dalsi vstupni data
+- docs/
|  \- ARENA_CHECKLIST.md   # checklist pro mereni v arene
+- experiment_tools/       # recorder, replay a evaluator
+- radar/                  # radar parser a pomocne utility
+- runs/
|  +- diagnostic/          # raw serial diagnostika
|  \- experiment/          # raw/fused MQTT zaznamy experimentu
+- test_soubory/           # simulacni a OptiTrack replay scenare
+- app.py                  # FastAPI + WebSocket vrstva
+- config.py               # centralni konfigurace
+- db_handler.py           # PostgreSQL vrstva
+- fusion.py               # online fusion logika
+- ingestion.py            # cteni senzoru a publikace raw dat
+- main.py                 # start celeho systemu
\- run_context.py          # interni runtime run_id sdileny za behu
```

## Pozadavky

- Python 3.11 nebo novejsi
- MQTT broker na `127.0.0.1:1883`
- PostgreSQL na `127.0.0.1:5432`
- databaze `sensor_data`
- uzivatel `postgres` / heslo `postgres`
- pro ostry beh fyzicke senzory na COM portech nastavenych v `config.py` nebo `FOUR_*`

## Instalace

Z korene projektu:

```powershell
cd C:\Users\kabup\OneDrive\Plocha\BP_\KÓD\Four
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Konfigurace

Vychozi hodnoty jsou v `config.py`. Vetsinu z nich lze prepsat pres `FOUR_*` environment variables.

Nejdulezitejsi:

```powershell
$env:FOUR_MQTT_HOST = "127.0.0.1"
$env:FOUR_MQTT_PORT = "1883"
$env:FOUR_DB_HOST = "127.0.0.1"
$env:FOUR_DB_PORT = "5432"
$env:FOUR_DB_NAME = "sensor_data"
$env:FOUR_DB_USER = "postgres"
$env:FOUR_DB_PASSWORD = "postgres"
$env:FOUR_API_HOST = "127.0.0.1"
$env:FOUR_API_PORT = "8000"
$env:FOUR_RUN_ID = "run_manual_001"
$env:FOUR_EXPERIMENT_LABEL = "dronarena"
$env:FOUR_CAPTURE_RAW_SERIAL = "1"
$env:FOUR_DIAGNOSTIC_CAPTURE_DIR = "C:\path\to\runs\diagnostic"
```

Porty a geometrie senzoru:

```powershell
$env:FOUR_BLE_1_PORT = "COM38"
$env:FOUR_BLE_2_PORT = "COM17"
$env:FOUR_RADAR_1_CFG_PORT = "COM13"
$env:FOUR_RADAR_1_DAT_PORT = "COM14"
$env:FOUR_RADAR_2_CFG_PORT = "COM11"
$env:FOUR_RADAR_2_DAT_PORT = "COM12"

$env:FOUR_BLE_1_POS_X = "1.5"
$env:FOUR_BLE_1_POS_Y = "0.0"
$env:FOUR_BLE_1_POS_Z = "0.8"
$env:FOUR_BLE_1_ROTATION = "90"
```

Cesta k radarovemu profilu:

```powershell
$env:FOUR_RADAR_CONFIG_FILE = "C:\path\to\profile.cfg"
```

Poznamky:

- `FOUR_CAPTURE_RAW_SERIAL` je aktualne vychozim nastavenim zapnute i bez env promenne.
- `record_experiment.py --label ...` samo nastavi aktivni runtime `run_id` pro bezici `main.py`.
- `run_context.py` je interni mechanismus, nespousti se rucne.

## PostgreSQL Pres Docker

V koreni nadrazeneho workspace je `docker-compose.yml`, ale zveda jen PostgreSQL. MQTT broker je potreba spustit zvlast.

Priklad:

```powershell
cd C:\Users\kabup\OneDrive\Plocha\BP_\KÓD
$env:POSTGRES_DB = "sensor_data"
$env:POSTGRES_USER = "postgres"
$env:POSTGRES_PASSWORD = "postgres"
$env:POSTGRES_PORT = "5432"
docker compose up -d
```

Pokud databaze `sensor_data` jeste neexistuje:

```powershell
psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE sensor_data;"
```

## Spusteni Systemu

Pred startem musi bezet PostgreSQL a MQTT broker.

```powershell
cd C:\Users\kabup\OneDrive\Plocha\BP_\KÓD\Four
.\.venv\Scripts\Activate.ps1
python main.py
```

Dashboard:

```text
http://127.0.0.1:8000
```

`main.py` spousti:

- ingestion worker pro radar/BLE vstupy a zapis do DB
- fusion loop pro clustering a parovani radar/BLE dat
- FastAPI server s dashboardem

Prakticky:

- kdyz nebezi MQTT broker, ingestion a fusion se nepripoji
- kdyz nebezi PostgreSQL, DB zapis nebude fungovat a `app.py` pri startu spadne
- kdyz neodpovidaji COM porty, workery se budou stale pokouset o reconnect

## Samostatne Spusteni Casti

Fusion:

```powershell
python fusion.py
```

Web/API:

```powershell
uvicorn app:app --host 127.0.0.1 --port 8000
```

Ingestion:

```powershell
python ingestion.py
```

## Testovaci Scenare

Ve `test_soubory/` jsou simulacni scenare, ktere generuji synteticka radarova a BLE mereni do stejneho MQTT rozhrani jako ostry system.

Prvni sanity check:

```powershell
cd C:\Users\kabup\OneDrive\Plocha\BP_\KÓD
python -m Four.test_soubory.test_01_linear_pass
```

Popis simulacnich scenaru je v `test_soubory/Popis_testu.md`. Prakticky checklist
pro mereni v arene je v [docs/ARENA_CHECKLIST.md](/C:/Users/kabup/OneDrive/Plocha/BP_/KÓD/Four/docs/ARENA_CHECKLIST.md:1).

## Replay OptiTrack XLSX

Pro data z Dronareny je pripraven replay OptiTrack exportu do stejne testovaci pipeline jako ostatni scenare.

Vychozi mapovani os:

- systemova `x <- x`
- systemova `y <- -z`
- systemova `z <- y`

Priklad:

```powershell
cd C:\Users\kabup\OneDrive\Plocha\BP_\KÓD
python -m Four.test_soubory.test_14_optitrack_replay --xlsx ".\Four\data\optitrack\test_dronaren.xlsx" --auto-fit-room
```

Uzitecne volby:

- `--objects Robot03 Robot04`
- `--frame-stride 6`
- `--max-frames 2000`
- `--speed 2.0`
- `--axis-x/--axis-y/--axis-z`
- `--offset-x/--offset-y/--offset-z`
- `--room-size-x/--room-size-y`

## Experiment Workflow

Workflow pro realne ladeni v Dronarene:

1. spustit `main.py`
2. pro kazdy test spustit `record_experiment --label ...`
3. od OptiTracku vzit odpovidajici `.xlsx`
4. doma pustit `replay_raw`
5. vyhodnotit novy fused vystup proti OptiTracku

Nejpohodlnejsi prakticky rezim:

```powershell
cd C:\Users\kabup\OneDrive\Plocha\BP_\KÓD\Four
python main.py
```

Pak pro kazdy jednotlivi beh:

```powershell
cd C:\Users\kabup\OneDrive\Plocha\BP_\KÓD
python -m Four.experiment_tools.record_experiment --label "static_01"
```

Pri dalsim testu jen zmenis label:

```powershell
python -m Four.experiment_tools.record_experiment --label "crossing_01"
```

`record_experiment.py` udela dve veci najednou:

- zacne nahravat MQTT provoz
- prepne aktivni `run_id` bez restartu `main.py`

Vystup se uklada do:

```text
Four\runs\experiment\<timestamp>_<label>\
```

Obsah:

- `raw.ndjson`
- `fused.ndjson`
- `metadata.json`

Replay raw dat:

```powershell
python -m Four.experiment_tools.replay_raw --input-dir ".\Four\runs\experiment\20260425_150000_static_01" --rate 1.0
```

Vyhodnoceni proti OptiTracku:

```powershell
python -m Four.experiment_tools.evaluate_optitrack `
  --input-dir ".\Four\runs\experiment\20260425_150000_static_01" `
  --xlsx ".\Four\data\optitrack\test_dronaren.xlsx" `
  --tag-map "AA1122334455=Drone"
```

Evaluator umi:

- automaticky odhadnout casovy posun
- porovnat fused vystup s ground truth
- ulozit `evaluation.json` do slozky experimentu

## Hlubsi Diagnostika Senzoru

Kdyz chces sbirat i nerozparserovana data z COM portu, nech zapnute `FOUR_CAPTURE_RAW_SERIAL=1` a spust normalne `main.py`.

Diagnosticke soubory se ukladaji do:

```text
Four\runs\diagnostic\<RUN_ID>\
```

Pri zmene `--label` v recorderu se dalsi diagnosticke zaznamy automaticky zacnou zapisovat do nove slozky bez restartu `main.py`.

Vzniknou soubory:

- `radar_1_serial.ndjson`
- `radar_2_serial.ndjson`
- `ble_1_serial.ndjson`
- `ble_2_serial.ndjson`
- `metadata.json`

Obsah:

- radar: `data_base64`, `bytes_len`, `parsed_ok`
- BLE: `data_base64`, `decoded_text`, `matched_pattern`

Tohle je vhodne pro ladeni situaci, kdy neni jasne, jestli problem vznikl uz na seriove vrstve, v parseru, nebo az ve fusion.

## Dulezite Cesty

- checklist do areny: [docs/ARENA_CHECKLIST.md](/C:/Users/kabup/OneDrive/Plocha/BP_/KÓD/Four/docs/ARENA_CHECKLIST.md:1)
- OptiTrack vstup: [data/optitrack/test_dronaren.xlsx](/C:/Users/kabup/OneDrive/Plocha/BP_/KÓD/Four/data/optitrack/test_dronaren.xlsx)
- experiment tools: [experiment_tools](/C:/Users/kabup/OneDrive/Plocha/BP_/KÓD/Four/experiment_tools)

## Overeni Syntaxe

Rychla kontrola Python souboru:

```powershell
python -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in pathlib.Path('.').rglob('*.py')]; print('OK')"
```

## Zname Technicke Dluhy

- `kalman_filter.py` existuje, ale hlavni fusion vrstva ho zatim nepouziva.
- hlavni moduly jsou stale v rootu projektu; pripadny presun do `core/` by byl dalsi samostatny refaktor.
