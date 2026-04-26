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
|  +- ARENA_CHECKLIST.md   # checklist pro mereni v arene
|  \- UPBOARD_START.md     # start pro 2x UP Board
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
- pro ostry beh fyzicke senzory na portech nastavenych v `config.py` nebo `FOUR_*`

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
$env:FOUR_NODE_ROLE = "all"
$env:FOUR_ENABLED_SENSORS = "radar_1,radar_2,ble_1,ble_2"
$env:FOUR_INGEST_ENABLE_DB = "1"
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
- `record_experiment.py --label ...` samo nastavi aktivni runtime `run_id` pro bezici procesy na stejnem filesystemu.
- `run_context.py` je interni mechanismus, nespousti se rucne.
- `FOUR_NODE_ROLE` umi oddelit rezimy `all`, `central`, `edge`, `ingestion`, `fusion`, `api`.
- `FOUR_ENABLED_SENSORS` omezi, ktere radar/BLE workery se opravdu spusti.
- `FOUR_INGEST_ENABLE_DB=0` vypne raw zapis do PostgreSQL, kdyz na edge nodu DB neni.

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
- kdyz neodpovidaji porty senzoru, workery se budou stale pokouset o reconnect

## Rezim 2x UP Board

Projekt umi bezet i rozdeleny na dva Linux nody:

- `central`: lokalni senzory `radar_1,ble_1`, MQTT broker, PostgreSQL, fusion a API
- `edge`: lokalni senzory `radar_2,ble_2`, jen ingestion a publish do MQTT na centralu

Aktualni laboratorni mapovani:

- `central` = `soniot@192.168.137.2`
- `edge` = `soniot1@192.168.138.2`

Doporuceny zpusob startu je pres hotove shell skripty:

Centralni UP board:

```bash
cd /cesta/k/Four
chmod +x scripts/start_up_central.sh
./scripts/start_up_central.sh
```

Edge UP board:

```bash
cd /cesta/k/Four
chmod +x scripts/start_up_edge.sh
./scripts/start_up_edge.sh <ip_centralniho_up>
```

Stejneho vysledku dosahnes i pres `python main.py`, ale jen kdyz predem spravne nastavis `FOUR_NODE_ROLE`, `FOUR_ENABLED_SENSORS`, `FOUR_INGEST_ENABLE_DB` a na edge i `FOUR_MQTT_HOST`. Samotne `python main.py` bez env promennych na `2x UP Board` neni spravny start, protoze vychozi role je `all`.

Poznamky:

- `edge` spousti jen ingestion.
- `central` spousti ingestion, fusion i API.
- na `central` musi pred startem bezet MQTT broker a PostgreSQL.
- na `edge` se DB nespousti a `FOUR_INGEST_ENABLE_DB` ma zustat `0`.
- vychozi Linux porty pro `radar_1` a `ble_1` v `config.py` odpovidaji beznemu laboratornimu zapojeni.
- vychozi Linux porty pro `radar_2` a `ble_2` jsou v `config.py` jen placeholdery a na edge je skoro vzdy potreba je prepsat pres `FOUR_RADAR_2_CFG_PORT`, `FOUR_RADAR_2_DAT_PORT` a `FOUR_BLE_2_PORT`.
- podrobny start je v `docs/UPBOARD_START.md`.

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
pro mereni v arene je v `docs/ARENA_CHECKLIST.md`.

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

1. spustit system
2. pro kazdy test spustit `record_experiment --label ...`
3. od OptiTracku vzit odpovidajici `.xlsx`
4. doma pustit `replay_raw`
5. vyhodnotit novy fused vystup proti OptiTracku

Nejpohodlnejsi prakticky rezim pro single-node:

```powershell
cd C:\Users\kabup\OneDrive\Plocha\BP_\KÓD\Four
python main.py
```

V rezimu `2x UP Board` timto krokem mysli:

- na `central` spustit `./scripts/start_up_central.sh`
- na `edge` spustit `./scripts/start_up_edge.sh <ip_centralu>`

Pak pro kazdy jednotlivi beh na PC nebo single-node:

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
- prepne aktivni `run_id` bez restartu bezicich procesu na stejnem filesystemu

V praxi:

- pro `raw.ndjson` a `fused.ndjson` staci recorder pusteny jen na centralu, protoze tam vidi cely MQTT provoz
- pro diagnostiku v `runs/diagnostic` se zmena `run_id` sama projevi jen na nodu, kde je zmenen stavovy soubor
- pokud bezi `edge` na vlastnim filesystemu, jeho serial diagnostika se sama na novy label neprepne

Pro `2x UP Board` je proto doporuceny start recorderu pres `scripts/record_sync.sh`, ktery:

- na `edge` zapise stejny label do `.active_run_id`
- na `centralu` spusti `record_experiment`

Priklad na `centralu` z rootu projektu:

```bash
cd ~/Four/Dronarena
chmod +x scripts/record_sync.sh
./scripts/record_sync.sh test_01 soniot1@192.168.138.2
```

Pokud projekt na Linuxu nelezi ve slozce `Four`, pouzivej lokalni modulovou cestu z rootu projektu:

```bash
cd /cesta/k/projektu
python -m experiment_tools.record_experiment --label "test_01"
```

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

Kdyz chces sbirat i nerozparserovana data ze seriovych portu, nech zapnute `FOUR_CAPTURE_RAW_SERIAL=1` a spust normalne `main.py`.

Diagnosticke soubory se ukladaji do:

```text
Four\runs\diagnostic\<RUN_ID>\
```

Pri zmene `--label` v recorderu se dalsi diagnosticke zaznamy automaticky zacnou zapisovat do nove slozky bez restartu `main.py`, ale jen na nodu, ktery vidi stejny `ACTIVE_RUN_ID_FILE`.

Prakticky:

- single-node nebo vse v jednom adresari: diagnostika se prepne automaticky
- `2x UP Board` s oddelenym filesystemem: recorder na centralu automaticky prepne central diagnostiku, ale ne edge diagnostiku
- pokud chces mit na edge diagnostiku rozdelenou po behach stejne jako na centralu, musis `run_id` synchronizovat i na edge nebo edge diagnostiku vypnout

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

- checklist do areny: `docs/ARENA_CHECKLIST.md`
- start pro 2x UP Board: `docs/UPBOARD_START.md`
- OptiTrack vstup: `data/optitrack/test_dronaren.xlsx`
- experiment tools: `experiment_tools/`

## Overeni Syntaxe

Rychla kontrola Python souboru:

```powershell
python -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in pathlib.Path('.').rglob('*.py')]; print('OK')"
```

## Zname Technicke Dluhy

- `kalman_filter.py` existuje, ale hlavni fusion vrstva ho zatim nepouziva.
- hlavni moduly jsou stale v rootu projektu; pripadny presun do `core/` by byl dalsi samostatny refaktor.
