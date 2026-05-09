# Four

Four je pipeline pro sber, fuzi a vizualizaci dat z radarovych a BLE senzoru.
Umi bezet jako jeden lokalni proces na Windows/Linuxu i rozdeleny mezi dva
UP boardy.

Aktualni datovy tok:

```text
radar/BLE senzory -> ingestion.py -> MQTT -> fusion.py -> MQTT -> app.py -> WebSocket -> index.html
```

`main.py` sklada ingestion, fusion a API do jednoho procesu. Jednotlive casti
ale porad komunikuji pres MQTT, takze je lze spoustet i oddelene podle role
uzlu.

## Co je v projektu

```text
Four/
+- data/optitrack/         # OptiTrack XLSX/CSV vstupy
+- docs/                   # provozni navody a rozcestnik dokumentace
+- experiment_tools/       # recorder, replay a offline scenario evaluace
+- radar/                  # radar parser, interface a cfg profily
+- runs/
|  +- diagnostic/          # raw serial dumpy senzoru
|  \- experiment/          # raw/fused MQTT zaznamy experimentu
+- scripts/                # start a synchronizacni shell skripty
+- app.py                  # FastAPI + dashboard + WebSocket bridge
+- config.py               # centralni runtime konfigurace
+- db_handler.py           # inicializace tabulek a DB write vrstva
+- fusion.py               # online fuzni logika
+- ingestion.py            # cteni senzoru a publish raw dat
+- main.py                 # hlavni vstupni bod
\- run_context.py          # sdilene runtime run_id mezi procesy
```

## Pozadavky

- Python 3.11+
- MQTT broker
- PostgreSQL pro role `all`, `central`, `fusion` a `api`
- fyzicke senzory nebo testovaci/replay vstup

Poznamky k databazi:

- `app.py` se pri startu vzdy pripojuje do PostgreSQL.
- `db_handler.py` si schema, tabulky a indexy vytvori samo pres
  `CREATE ... IF NOT EXISTS`.
- `edge` muze bezet bez DB, pokud ma `FOUR_INGEST_ENABLE_DB=0`.

## Instalace

Z adresare `Four/`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Zavisle sluzby

V nadrazenem adresari je `docker-compose.yml` pouze pro PostgreSQL:

```powershell
cd ..
$env:POSTGRES_DB = "sensor_data"
$env:POSTGRES_USER = "postgres"
$env:POSTGRES_PASSWORD = "postgres"
$env:POSTGRES_PORT = "5432"
docker compose up -d
```

Vychozi `docker-compose.yml` bez env promennych pouzije jmena `app_db`,
`app_user`, `app_password`. Pokud chces vychozi `config.py` bez dalsich zmen,
nastav promenne jako v prikladu vyse.

MQTT broker se spousti zvlast. Vychozi konfigurace projektu ceka broker na
`127.0.0.1:1883`.

## Konfigurace

Vetsinu runtime nastaveni lze prepsat pres `FOUR_*` environment variables.
Hlavni jsou:

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
$env:FOUR_EXPERIMENT_LABEL = "laborator_03"
$env:FOUR_CAPTURE_RAW_SERIAL = "1"
```

Senzory: porty a geometrie

Porty:

```powershell
$env:FOUR_BLE_1_PORT = "COM38"
$env:FOUR_BLE_2_PORT = "COM17"
$env:FOUR_RADAR_1_CFG_PORT = "COM13"
$env:FOUR_RADAR_1_DAT_PORT = "COM14"
$env:FOUR_RADAR_2_CFG_PORT = "COM11"
$env:FOUR_RADAR_2_DAT_PORT = "COM12"
```

Aktualni defaulty geometrie v `config.py` pro laboratorni/Dronarena setup:

```powershell
$env:FOUR_BLE_1_POS_X = "3.15"
$env:FOUR_BLE_1_POS_Y = "0.0"
$env:FOUR_BLE_1_POS_Z = "1.0"
$env:FOUR_BLE_1_ROTATION = "90"

$env:FOUR_BLE_2_POS_X = "0.0"
$env:FOUR_BLE_2_POS_Y = "3.95"
$env:FOUR_BLE_2_POS_Z = "1.0"
$env:FOUR_BLE_2_ROTATION = "0"

$env:FOUR_RADAR_1_POS_X = "3.05"
$env:FOUR_RADAR_1_POS_Y = "0.0"
$env:FOUR_RADAR_1_POS_Z = "1.0"
$env:FOUR_RADAR_1_ROTATION = "0"

$env:FOUR_RADAR_2_POS_X = "0.0"
$env:FOUR_RADAR_2_POS_Y = "4.05"
$env:FOUR_RADAR_2_POS_Z = "1.0"
$env:FOUR_RADAR_2_ROTATION = "-90"
```

Vyznam poli:

- `POS_X`, `POS_Y`, `POS_Z`: globalni poloha senzoru v metrech v mape mistnosti.
- `ROTATION`: natoceni senzoru ve stupnich v rovine XY.
- `0` znamena smer do `+X`, `90` do `+Y`, `-90` do `-Y`, `180` nebo `-180` do `-X`.

Jak se to pouziva v kodu:

- radar: lokalni souradnice bodu se otoci o `ROTATION` a pak se k nim pricte `POS_X/Y/Z`
  v [ingestion.py](</C:/Users/kabup/OneDrive/Plocha/BP_/KÓD/Four/ingestion.py:292>)
- BLE: `POS_X/Y/Z` je poloha kotvy a `ROTATION` je smer, od ktereho se pocita
  azimut pro triangulaci v [fusion.py](</C:/Users/kabup/OneDrive/Plocha/BP_/KÓD/Four/fusion.py:438>)

Dulezite:

- tohle nejsou "spravne hodnoty obecne", ale aktualni defaulty z repozitare
- v arene je potreba senzory zmerit a hodnoty prepsat pres `FOUR_*`
- kdyz zmenis fyzicke rozmisteni senzoru a neprepises geometrii, fused vystup
  bude posunuty nebo natoceny spatne
- README neber jako kalibracni protokol; autoritativni zdroj je `config.py`
  a skutecne zamerene pozice pri mereni

Radarove profily:

```powershell
$env:FOUR_RADAR_CONFIG_FILE = "C:\path\to\profile.cfg"
$env:FOUR_RADAR_BOOTSTRAP_CONFIG_FILE = "C:\path\to\bootstrap_profile.cfg"
```

Role uzlu:

- `all`: ingestion + fusion + API
- `central`: ingestion + fusion + API
- `edge`: jen ingestion
- `ingestion`: jen ingestion
- `fusion`: jen fusion
- `api`: jen FastAPI/dashboard

## Rychly start: single-node

Pred startem musi bezet PostgreSQL a MQTT broker.

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

Dashboard:

```text
http://127.0.0.1:8000
```

`main.py` pri roli `all` spousti:

- ingestion worker pro radar/BLE vstupy
- fusion loop
- FastAPI server s dashboardem

Pokud nebezi MQTT broker, ingestion ani fusion se nepripoji. Pokud nebezi
PostgreSQL, `app.py` spadne pri startu.

## 2x UP Board

Projekt umi rozdeleni na dva uzly:

- `central`: lokalni senzory `radar_1,ble_1`, MQTT broker, PostgreSQL, fusion a API
- `edge`: lokalni senzory `radar_2,ble_2`, jen ingestion a publish do MQTT na central

Start skripty:

```bash
./scripts/start_up_central.sh
./scripts/start_up_edge.sh <ip_centralu>
```

Skripty nastavuji spravne `FOUR_NODE_ROLE`, `FOUR_ENABLED_SENSORS` a
`FOUR_INGEST_ENABLE_DB`. Aktualni detaily jsou v `docs/operations/UPBOARD_START.md`.

Dulezite:

- na `central` musi pred startem bezet MQTT broker a PostgreSQL
- `edge` ma bezet s `FOUR_INGEST_ENABLE_DB=0`
- vychozi Linux porty pro `radar_2` a `ble_2` jsou placeholdery a typicky je
  nutne je prepsat pres env promenne

## Samostatne spusteni casti

Z adresare `Four/`:

```powershell
python ingestion.py
python fusion.py
uvicorn app:app --host 127.0.0.1 --port 8000
```

Tohle je uzitecne hlavne pri ladeni jednotlivych vrstev.

## Experiment workflow

Prubeh realneho mereni:

1. spustit system (`python main.py` nebo UP board skripty)
2. spustit recorder s labelem behu
3. po mereni pripadne prehrat `raw.ndjson`
4. porovnat fused vystup s OptiTrack daty

Recorder:

```powershell
python -m experiment_tools.record_experiment --label "static_01"
```

Recorder:

- zacne nahravat `sensors/raw/#` a `sensors/fused`
- prepne aktivni `run_id` v `.active_run_id`
- ulozi vystup do `runs/experiment/<timestamp>_<label>/`

Vystup obsahuje:

- `raw.ndjson`
- `fused.ndjson`
- `metadata.json`

V rezimu `2x UP Board` je pro synchronizaci `run_id` na edge k dispozici:

```bash
./scripts/record_sync.sh test_01 <edge_host>
```

## Replay a vyhodnoceni

Replay raw zaznamu:

```powershell
python -m experiment_tools.replay_raw --input-dir ".\runs\experiment\20260425_150000_static_01" --rate 1.0
```

Replay raw zaznamu soucasne s OptiTrack referenci v samostatnem dashboard modu:

```powershell
python -m experiment_tools.replay_raw `
  --input-dir ".\runs\experiment\20260425_150000_static_01" `
  --rate 1.0 `
  --with-optitrack-reference `
  --optitrack-input ".\data\optitrack\Take 2026-05-05 11.47.22 AM.csv"
```

Jednim souborem pro porovnani v dashboardu:

```powershell
python .\experiment_tools\replay_compare.py
```

`replay_compare.py` je pohodlny wrapper nad `replay_raw.py` s predvyplnenym
OptiTrack nastavenim pro aktualni Dronarenu. Dnes ma natvrdo vybrany vstupni
CSV soubor, transformaci souradnic, casovy posun a `--optitrack-start-on-body Phantom4`.
Pro jiny experiment nebo jiny startovni objekt tyto hodnoty prepis parametry
na prikazove radce. Rucni override casoveho posunu:

```powershell
python .\experiment_tools\replay_compare.py --optitrack-delay-sec 75.35
```

### Scenario evaluation pipeline

Pro porovnani jednotlivych kombinaci senzoru proti OptiTracku je v projektu
nova offline pipeline:

1. `split_scenarios.py`
2. `run_offline_fusion.py`
3. `evaluate_all.py`

Nejjednodussi spusteni vseho najednou:

```powershell
.\experiment_tools\run_scenario_pipeline.ps1 `
  -RunDir .\runs\experiment\20260507_104346_Dronarena_04
```

Kdyz PowerShell blokuje lokalni skripty:

```powershell
powershell -ExecutionPolicy Bypass -File .\experiment_tools\run_scenario_pipeline.ps1 `
  -RunDir .\runs\experiment\20260507_104346_Dronarena_04
```

Rucni spusteni po krocich:

```powershell
python .\experiment_tools\split_scenarios.py `
  --run-dir .\runs\experiment\20260507_104346_Dronarena_04

python .\experiment_tools\run_offline_fusion.py `
  --run-dir .\runs\experiment\20260507_104346_Dronarena_04

python .\experiment_tools\evaluate_all.py `
  --run-dir .\runs\experiment\20260507_104346_Dronarena_04 `
  --optitrack-csv .\data\optitrack\Take_2026-05-07_12.43.55_PM_Final.csv
```

Testovane scenare:

- `ble1`
- `ble2`
- `radar1`
- `radar2`
- `radar1_ble1`
- `radar2_ble2`
- `2x_radar`
- `2x_radar_ble1`
- `2x_radar_ble2`
- `2x_ble`
- `radar1_2x_ble`
- `radar2_2x_ble`
- `fusion`

Pipeline vytvori:

- `runs/experiment/<RUN>/scenario_splits/<scenario>/raw.ndjson`
- `runs/experiment/<RUN>/scenario_splits/<scenario>/fused.ndjson`
- `runs/experiment/<RUN>/scenario_splits/<scenario>/position_eval/`
- `runs/experiment/<RUN>/scenario_splits/<scenario>/ble_only_eval/`
- `runs/experiment/<RUN>/scenario_splits/_summary/`

Vyhodnoceni je rozdelene na dve metodiky:

- `position`
  - pro scenare hodnocene v hlavni 3D sekci
  - `radar1`, `radar2`, `2x_radar`, `2x_ble`, `radar1_2x_ble`, `radar2_2x_ble`, `fusion`
- `radar_ble_single_anchor`
  - pro `radar1_ble1`, `radar2_ble2`, `2x_radar_ble1` a `2x_radar_ble2`
  - offline vybere radar cluster nejblizsi BLE paprsku jedne kotvy
- `ble_only`
  - pro `ble1` a `ble2`
  - nepouziva 3D pozici, ale:
    - vzdalenost GT bodu od BLE paprsku
    - uhlovou chybu mezi BLE paprskem a smerem na GT

Souhrny jsou v:

- `scenario_splits/_summary/position/tables/`
- `scenario_splits/_summary/position/boxplots/`
- `scenario_splits/_summary/radar_ble_single_anchor/tables/`
- `scenario_splits/_summary/radar_ble_single_anchor/boxplots/`
- `scenario_splits/_summary/ble_only/tables/`
- `scenario_splits/_summary/ble_only/boxplots/`

Per-scenario detail:

- `position_eval/`
  - `stats_[Objekt].json`
  - `[scenar]_[objekt]_2D_map.jpg`
  - `[scenar]_[objekt]_error_timeline.jpg`
  - `[scenar]_[objekt]_axes_timeline.jpg`
- `single_anchor_eval/`
  - `stats_single_anchor_[Objekt].json`
  - `[scenar]_[objekt]_2D_map.jpg`
  - `[scenar]_[objekt]_error_timeline.jpg`
  - `[scenar]_[objekt]_axes_timeline.jpg`
  - `[scenar]_[objekt]_cluster_ray_distance_timeline.jpg`
- `ble_only_eval/`
  - `stats_ble_only_[Objekt].json`
  - `[scenar]_[objekt]_ray_distance_timeline.jpg`
  - `[scenar]_[objekt]_angle_error_timeline.jpg`

Interpretace:

- `radar-only` scenare jsou vyhodnocene pres anonymni radar track/clustery
  sparovane na GT v case.
- `ble1` a `ble2` nejsou v hlavni 3D tabulce, protoze jednotlive BLE kotvy
  samy nevytvareji plnou 3D pozici cile.
- `radar1_ble1`, `radar2_ble2`, `2x_radar_ble1` a `2x_radar_ble2`
  nejsou v hlavni 3D tabulce.
  Hodnoti se zvlast pres offline heuristiku `nearest radar cluster to BLE ray`.
- `scenario_splits/_summary/README.txt` obsahuje kratke vysvetleni struktury
  primo vedle vygenerovanych vystupu.

### Aktualni referencni beh

V repozitari je uz hotove vyhodnoceni behu:

- `runs/experiment/20260507_104346_Dronarena_04/`

Pouzita OptiTrack reference:

- `data/optitrack/Take_2026-05-07_12.43.55_PM_Final.csv`

Hotove souhrny jsou v:

- `runs/experiment/20260507_104346_Dronarena_04/scenario_splits/_summary/`

Nejdulezitejsi vystupy:

- `position/tables/summary_table_Phantom4.csv`
- `position/tables/summary_table_Vysavac3.csv`
- `ble_only/tables/summary_table_ble_only_Phantom4.csv`
- `ble_only/tables/summary_table_ble_only_Vysavac3.csv`

Strucne vysledky teto analyzy:

- `Phantom4`
  - nejlepsi 3D scenar: `2x_radar`, `rmse_3d_m = 0.397`
  - nejlepsi BLE-only scenar: `ble2`, `rmse_ray_distance_m = 0.375`
- `Vysavac3`
  - nejlepsi 3D scenar: `radar1`, `rmse_3d_m = 0.234`
  - nejlepsi BLE-only scenar: `ble1`, `rmse_ray_distance_m = 0.331`

Dulezite:

- `scenario_splits/` je generovany vystup pipeline, ne puvodni namerena data
- kdykoliv ho lze smazat a znovu vytvorit pres `run_scenario_pipeline.ps1`

## OptiTrack replay

`experiment_tools.optitrack_replay` umi prehrat OptiTrack jako samostatnou
dashboard referenci bez synthetic radar/BLE vrstvy.

Tohle je pomocny replay workflow pro dashboard.
Pro scenario evaluaci `Dronarena_04` pouzij sekci `Scenario evaluation pipeline`
vyse a referencni CSV `Take_2026-05-07_12.43.55_PM_Final.csv`.

Priklad:

```powershell
python -m experiment_tools.optitrack_replay `
  --input ".\data\optitrack\Take 2026-05-05 11.47.22 AM.csv" `
  --axis-x -x `
  --axis-y z `
  --axis-z y `
  --yaw-deg -89.4461 `
  --offset-x 2.6268 `
  --offset-y 3.8304 `
  --offset-z -0.1569 `
  --start-on-body Phantom4
```

## Diagnostika senzoru

Kdyz zustane zapnute `FOUR_CAPTURE_RAW_SERIAL=1`, ingestion uklada i
neroztazene serial vystupy do:

```text
runs/diagnostic/<RUN_ID>/
```

Typicke soubory:

- `radar_1_serial.ndjson`
- `radar_2_serial.ndjson`
- `ble_1_serial.ndjson`
- `ble_2_serial.ndjson`
- `metadata.json`

To je uzitecne pro oddeleni problemu na vrstve portu, parseru a fusion logiky.

## Dulezite dokumenty

Kdyz potrebujes rychly vstup do projektu, otevri nejdriv:

- `docs/README.md`
- `experiment_tools/README.md`
- `docs/operations/README.md`
- `docs/operations/ARENA_CHECKLIST.md`
- `docs/evaluation/README.md`
- `docs/evaluation/SCENARIO_EVALUATION.md`
- `docs/operations/UPBOARD_START.md`
- `experiment_tools/run_scenario_pipeline.ps1`
- `experiment_tools/split_scenarios.py`
- `experiment_tools/run_offline_fusion.py`
- `experiment_tools/evaluate_all.py`
- `experiment_tools/optitrack_replay.py`
- `data/optitrack/Take_2026-05-07_12.43.55_PM_Final.csv`

## Rychla kontrola syntaxe

```powershell
python -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in pathlib.Path('.').rglob('*.py')]; print('OK')"
```
