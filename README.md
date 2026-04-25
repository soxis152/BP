# Four - Distributed Radar + BLE Fusion on Two UP Boards

Projekt `Four` je distribuovany system pro sber, fuzi, ukladani a vizualizaci dat
ze dvou typu senzoru:

- radar AWR2944
- BLE kotvy s azimutem a elevaci

Typicke nasazeni pouziva dva uzly:

- `UP1` jako centralni node
- `UP2` jako edge node a internet gateway

PC se pripojuje na `UP1`, odkud se otevira dashboard. `UP2` sbira data z druhe
sady senzoru a posila je pres sit na `UP1`, kde probiha fusion, zapis do
PostgreSQL a webove zobrazeni.

## Co Projekt Dela

Projekt sklada dohromady cely retezec:

```text
fyzicke senzory / simulatory
    -> ingestion.py
    -> MQTT topics sensors/raw/#
    -> fusion.py
    -> MQTT topic sensors/fused
    -> app.py
    -> WebSocket /ws
    -> index.html dashboard
```

Vedle toho se raw i fused data ukladaji do PostgreSQL pro pozdejsi analyzu.

## Hlavni Komponenty

- `ingestion.py`
  - cte radar a BLE seriove porty
  - posila radar konfiguraci do radaru pres cfg port
  - prevadi radarove body do globalnich souradnic mistnosti
  - publikuje raw data do MQTT topicu `sensors/raw/*`
  - volitelne uklada raw data do PostgreSQL
- `fusion.py`
  - cte `sensors/raw/#`
  - trianguluje BLE tag z dvojice BLE kotev
  - seskupuje radar body do clusteru
  - paruje BLE pozice s radar clustery
  - drzi kratkou `pair_memory` pro stabilnejsi identitu
  - publikuje vysledny snapshot do `sensors/fused`
  - uklada vzorkovana fused data do tabulky `fused_data`
- `app.py`
  - servirovani `index.html`
  - posloucha `sensors/fused`
  - preposila data dashboardu pres WebSocket
- `db_handler.py`
  - vytvari schema, tabulky a indexy
  - zprostredkovava davkove zapisy do PostgreSQL
- `main.py`
  - sklada ingestion, fusion a API dohromady
  - podle `FOUR_NODE_ROLE` spousti odpovidajici casti systemu
- `test_soubory/*`
  - simulacni scenare, ktere posilaji synteticka radarova a BLE data do stejneho
    MQTT rozhrani jako realne senzory

## Sitova Architektura

Sitova cast vychazi z prilozeneho diagramu.

### Topologie

```text
PC (management)
  192.168.137.1/24
        |
        | 192.168.137.0/24
        |
UP1 (central node)
  enp2s0 = 192.168.137.2
  eno1   = 192.168.138.1
        |
        | 192.168.138.0/24
        |
UP2 (gateway / edge node)
  enp2s0 = 192.168.138.2
  eno1   = DHCP z routeru, napr. 192.168.0.135
        |
        | 192.168.0.0/24
        |
Router / Internet
  LAN = 192.168.0.1
```

### Role Uzlu

- `PC`
  - management klient
  - pristup na dashboard bezici na `UP1`
- `UP1`
  - centralni node
  - MQTT broker
  - PostgreSQL
  - fusion
  - FastAPI + dashboard
  - volitelne take lokalni ingestion pro `radar_1` a `ble_1`
- `UP2`
  - edge node
  - ingestion pro `radar_2` a `ble_2`
  - default route do internetu
  - gateway pro `UP1`

### IP Addressing

| Device | Interface | IP Address | Network | Role |
| --- | --- | --- | --- | --- |
| PC | Ethernet | 192.168.137.1 | 192.168.137.0/24 | Management client |
| UP1 (Central) | enp2s0 | 192.168.137.2 | 192.168.137.0/24 | To PC |
| UP1 (Central) | eno1 | 192.168.138.1 | 192.168.138.0/24 | To UP2 |
| UP2 (Gateway) | enp2s0 | 192.168.138.2 | 192.168.138.0/24 | To UP1 |
| UP2 (Gateway) | eno1 | DHCP (e.g. 192.168.0.135) | 192.168.0.0/24 | To Router / Internet |
| Router | LAN | 192.168.0.1 | 192.168.0.0/24 | Internet gateway |

### Routing

#### UP2 (Gateway)

- default route: via router on `eno1`
- route to PC network: `192.168.137.0/24 via 192.168.138.1`
- IP forwarding enabled
- NAT (MASQUERADE) on interface `eno1`

#### UP1 (Central)

- default route: `default via 192.168.138.2`

#### PC

- static route: `192.168.138.0/24 via 192.168.137.2`

### Priklady Sitovych Prikazu

Enable IP forwarding on Linux:

```bash
net.ipv4.ip_forward=1
```

NAT on `UP2`:

```bash
iptables -t nat -A POSTROUTING -o eno1 -j MASQUERADE
```

Route on `UP2`:

```bash
ip route add 192.168.137.0/24 via 192.168.138.1
```

Default gateway on `UP1`:

```bash
ip route add default via 192.168.138.2
```

Persistent route on Windows PC:

```powershell
route -p add 192.168.138.0 mask 255.255.255.0 192.168.137.2
```

### Ocekavana Konektivita

| Source | Destination | Result |
| --- | --- | --- |
| PC | UP1 | OK |
| PC | UP2 | OK |
| UP1 | UP2 | OK |
| UP2 | Internet | OK |
| UP1 | Internet (via UP2) | OK |

## Kde Co Bezi

Nejcastejsi produkcni rozdeleni vypada takto:

### UP1 - central node

- `FOUR_NODE_ROLE=central`
- `FOUR_ENABLED_SENSORS=radar_1,ble_1`
- `FOUR_MQTT_HOST=127.0.0.1`
- `FOUR_DB_HOST=127.0.0.1`
- spousti:
  - ingestion pro lokalni senzory `radar_1`, `ble_1`
  - fusion
  - API/dashboard
  - DB worker

### UP2 - edge node

- `FOUR_NODE_ROLE=edge`
- `FOUR_ENABLED_SENSORS=radar_2,ble_2`
- `FOUR_MQTT_HOST=192.168.138.1`
- `FOUR_INGEST_ENABLE_DB=0`
- spousti:
  - ingestion pro `radar_2`, `ble_2`
- nespousti:
  - fusion
  - API
  - lokalni PostgreSQL zapis

### PC

- otevira dashboard na `http://192.168.137.2:8000`
- muze overovat routovani a dostupnost obou UP boardu

## Projektova Struktura

```text
Four/
  app.py
  config.py
  db_handler.py
  db_stats.py
  fusion.py
  index.html
  ingestion.py
  kalman_filter.py
  main.py
  requirements.txt
  radar/
    radar_interface.py
    parser_mmw_demo.py
    detected_object.py
    tdm/
    ddm/
  test_soubory/
    scenario_common.py
    test_01_linear_pass.py
    ...
    test_13_forklift_brake.py
```

## Pozadavky

### Software

- Python 3.11 nebo novejsi
- PostgreSQL
- MQTT broker
- `pip` a virtualni prostredi `venv`

Projekt je psany primarne pro Linux na UP boardech, ale cast vyvoje a
spousteni je podporena i na Windows. `main.py`, `app.py` a `fusion.py` na
Windows explicitne nastavuji `WindowsSelectorEventLoopPolicy`.

### Python Zavislosti

Z `requirements.txt`:

- `aiomqtt`
- `asyncpg`
- `fastapi`
- `uvicorn[standard]`
- `paho-mqtt`
- `pyserial`
- `numpy`
- `matplotlib`

### Hardware

Pro ostry beh:

- 2x radar AWR2944 nebo kompatibilni radarove jednotky
- 2x BLE kotva poskytujici `+UUDF` azimut/elevace vystup
- seriove porty pro cfg/data kanaly radaru
- seriove porty pro BLE kotvy

## Instalace

Z korene projektu `Four`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Na Linuxu:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## PostgreSQL A MQTT

Projekt potrebuje dve externi sluzby:

- PostgreSQL
- MQTT broker

### PostgreSQL

Vychozi DB konfigurace v `config.py`:

- host: `127.0.0.1`
- port: `5432`
- database: `sensor_data`
- user: `postgres`
- password: `postgres`

Databazi je potreba vytvorit pred prvnim spustenim:

```powershell
psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE sensor_data;"
```

Ve workspace je k dispozici i root `docker-compose.yml`, ale obsahuje jen
PostgreSQL service. Vychozi hodnoty v nem jsou jine nez v `config.py`, proto je
nutne bud:

- upravit environment promene pro compose
- nebo nastavit odpovidajici `FOUR_DB_*` promenne pro aplikaci

Priklad kompatibilniho spusteni compose z nadrazene slozky:

```powershell
$env:POSTGRES_DB="sensor_data"
$env:POSTGRES_USER="postgres"
$env:POSTGRES_PASSWORD="postgres"
docker compose up -d
```

### MQTT Broker

MQTT broker musi byt dostupny na adrese z `FOUR_MQTT_HOST` a `FOUR_MQTT_PORT`.
Vychozi nastaveni je:

- host: `127.0.0.1`
- port: `1883`

V produkcnim dvouuzlovem nasazeni typicky bezi MQTT broker na `UP1` a `UP2`
publikuje raw data na adresu `192.168.138.1`.

## Konfigurace

Centralni konfigurace je v `config.py`. Vetsinu hodnot lze prepsat pres
environment variables.

### Zakladni Promenne

| Variable | Default | Meaning |
| --- | --- | --- |
| `FOUR_NODE_ROLE` | `central` | rezim uzlu: `all`, `central`, `edge`, `ingestion`, `fusion`, `api` |
| `FOUR_ENABLED_SENSORS` | `radar_1,ble_1` | ktere senzory ma ingestion opravdu spustit |
| `FOUR_INGEST_ENABLE_DB` | `1` | zda ingestion zapisuje raw data do DB |
| `FOUR_RUN_ID` | `run_YYYYMMDD_HHMMSS` | identifikator aktualniho behu |
| `FOUR_MQTT_HOST` | `127.0.0.1` | MQTT broker host |
| `FOUR_MQTT_PORT` | `1883` | MQTT broker port |
| `FOUR_API_HOST` | `0.0.0.0` | bind adresa FastAPI |
| `FOUR_API_PORT` | `8000` | port dashboardu |
| `FOUR_RADAR_CONFIG_FILE` | `radar/tdm/AWR294X_profile_2025_11_07T16_27_59_226 copy2.cfg` | radar cfg soubor |

### Databazove Promenne

| Variable | Default |
| --- | --- |
| `FOUR_DB_HOST` | `127.0.0.1` |
| `FOUR_DB_PORT` | `5432` |
| `FOUR_DB_NAME` | `sensor_data` |
| `FOUR_DB_USER` | `postgres` |
| `FOUR_DB_PASSWORD` | `postgres` |
| `FOUR_DB_SCHEMA` | `public` |
| `FOUR_DB_POOL_MIN_SIZE` | `1` |
| `FOUR_DB_POOL_MAX_SIZE` | `5` |
| `FOUR_DB_COMMAND_TIMEOUT` | `60.0` |
| `FOUR_DB_BATCH_SIZE` | `100` |
| `FOUR_DB_FLUSH_SECONDS` | `1.0` |

### BLE Promenne

Pro kazdou BLE kotvu lze nastavit:

- port a baud:
  - `FOUR_BLE_1_PORT`, `FOUR_BLE_1_BAUD`
  - `FOUR_BLE_2_PORT`, `FOUR_BLE_2_BAUD`
- poloha a orientace:
  - `FOUR_BLE_1_POS_X`, `FOUR_BLE_1_POS_Y`, `FOUR_BLE_1_POS_Z`, `FOUR_BLE_1_ROTATION`
  - `FOUR_BLE_2_POS_X`, `FOUR_BLE_2_POS_Y`, `FOUR_BLE_2_POS_Z`, `FOUR_BLE_2_ROTATION`

Vychozi geometrie:

- `ble_1`: `(1.5, 0.0, 0.8)`, rotace `90`
- `ble_2`: `(0.0, 1.5, 0.8)`, rotace `0`

### Radar Promenne

Pro kazdy radar lze nastavit:

- porty:
  - `FOUR_RADAR_1_CFG_PORT`, `FOUR_RADAR_1_DAT_PORT`
  - `FOUR_RADAR_2_CFG_PORT`, `FOUR_RADAR_2_DAT_PORT`
- poloha a orientace:
  - `FOUR_RADAR_1_POS_X`, `FOUR_RADAR_1_POS_Y`, `FOUR_RADAR_1_POS_Z`, `FOUR_RADAR_1_ROTATION`
  - `FOUR_RADAR_2_POS_X`, `FOUR_RADAR_2_POS_Y`, `FOUR_RADAR_2_POS_Z`, `FOUR_RADAR_2_ROTATION`

Vychozi geometrie:

- `radar_1`: `(1.5, 0.0, 0.8)`, rotace `0`
- `radar_2`: `(0.0, 1.5, 0.8)`, rotace `-90`

## MQTT Topicy

Raw data:

```text
sensors/raw/radar_1
sensors/raw/radar_2
sensors/raw/ble_1
sensors/raw/ble_2
```

Fused data:

```text
sensors/fused
```

### Tvar Zprav

Radar raw payload:

```json
{
  "timestamp": 1710000000.0,
  "x": 1.23,
  "y": 0.87,
  "z": 0.91,
  "snr": 17.4,
  "doppler": -0.12
}
```

BLE raw payload:

```json
{
  "timestamp": 1710000000.0,
  "tag_id": "A1B2C3D4E5F6",
  "rssi": -67,
  "azimuth": 12.5,
  "elevation": 4.2
}
```

`sensors/fused` obsahuje:

- `radar`
- `radar_clusters`
- `ble`
- `objects`
- `stats`

Frontend dostava v jednom snapshotu jak diagnostiku, tak vysledne objekty.

## Databazove Tabulky

Pri startu se automaticky vytvareji tabulky:

- `ble_1`
- `ble_2`
- `radar_1`
- `radar_2`
- `fused_data`

### Schema

| Table | Columns |
| --- | --- |
| `ble_1`, `ble_2` | `run_id`, `timestamp`, `tag_id`, `rssi`, `azimuth`, `elevation` |
| `radar_1`, `radar_2` | `run_id`, `timestamp`, `x`, `y`, `z`, `snr`, `doppler` |
| `fused_data` | `run_id`, `timestamp`, `tag_id`, `x`, `y`, `z`, `confidence` |

Vytvareji se i indexy nad:

- `timestamp`
- `tag_id`
- kombinaci `tag_id, timestamp`
- kombinaci `run_id, timestamp`

## Jak Funguje Ingestion

### Radar

- `ingestion.py` nejprve posle radarovy cfg soubor na `cfg_port`
- radarovy datovy stream se cte z `dat_port` na `921600`
- parser vraci detekovane body
- body se transformuji z lokalnich souradnic do globalni mapy mistnosti
- jednoduchy gate odfiltruje body mimo sledovanou oblast:
  - `x` v intervalu `-0.5 .. 3.5`
  - `y` v intervalu `-0.5 .. 3.5`
  - `z` v intervalu `0.0 .. 2.5`

### BLE

- BLE worker cte seriovy vystup po radcich
- hleda ramec podle regexu `+UUDF:...`
- z payloadu bere:
  - `tag_id`
  - `rssi`
  - `azimuth`
  - `elevation`

## Jak Funguje Fusion

Aktualni fusion logika neni plny tracker. Je to online heuristika ladena pro
malou mistnost cca `3 x 3 m`.

### Kroky Fusion

1. `fusion.py` cte raw data z MQTT.
2. BLE tagy z `ble_1` a `ble_2` trianguluje do 3D bodu.
3. Radar body seskupuje jednoduchym clusteringem.
4. BLE pozice paruje s nejblizsim vhodnym radar clusterem.
5. `pair_memory` drzi kratkou pamet na drive sparovane tagy.
6. Pri kratkem vypadku radaru umi objekt prejit do `radar_ble_coasting`.
7. Nesparovane BLE zustavaji jako `ble_only`.
8. Nesparovane radar clustery zustavaji jako `radar_cluster`.

### Dulezite Konstanty

Vybrane prahy ve `fusion.py`:

- `RADAR_CLUSTER_DISTANCE = 0.45`
- `RADAR_CLUSTER_MAX_DZ = 0.40`
- `RADAR_CLUSTER_MIN_POINTS = 3`
- `RADAR_BLE_PAIR_MAX_DISTANCE = 1.0`
- `RADAR_BLE_PAIR_HOLD_SECONDS = 8.0`
- `RADAR_BLE_REACQUIRE_DISTANCE = 0.8`
- `RADAR_BLE_LOCK_MAX_DISTANCE = 1.35`
- `RADAR_BLE_COAST_SECONDS = 0.6`
- `BLE_TAG_TTL_SECONDS = 4.0`

## Dashboard

Dashboard je jednosouborovy `index.html`, bez build kroku a bez `npm`.

Zobrazuje:

- 2D a 3D pohled
- live objekty
- radar-only clustery
- BLE-only objekty
- radar + BLE sparovane objekty
- diagnostiku fusion pipeline
- confidence a pairing metadata

Hlavni endpointy:

- `GET /` - dashboard HTML
- `WS /ws` - live stream fused snapshotu

## Spusteni

### Varianta A - vse na jednom stroji

Vhodne pro lokalni demo nebo simulace.

1. Spust PostgreSQL.
2. Spust MQTT broker.
3. Nastav promene podle potreby.
4. Spust `main.py`.

Priklad:

```powershell
$env:FOUR_NODE_ROLE="all"
$env:FOUR_ENABLED_SENSORS="radar_1,radar_2,ble_1,ble_2"
python main.py
```

Pokud nepouzivas fyzicke senzory, ale simulace, muze `main.py` bezet i bez
realnych portu tehdy, kdy ingestion nepotrebujes. V takovem pripade spust jen:

```powershell
$env:FOUR_NODE_ROLE="central"
$env:FOUR_ENABLED_SENSORS=""
python main.py
```

Poznamka: v produkci central role standardne spousti i ingestion. Pokud nechces
na centralnim uzlu otvirat seriove porty, pouzij radsi samostatne procesy
`fusion.py` a `uvicorn app:app`.

### Varianta B - realne nasazeni na UP1 + UP2

#### UP1

```bash
export FOUR_NODE_ROLE=central
export FOUR_ENABLED_SENSORS=radar_1,ble_1
export FOUR_MQTT_HOST=127.0.0.1
export FOUR_DB_HOST=127.0.0.1
export FOUR_DB_NAME=sensor_data
export FOUR_DB_USER=postgres
export FOUR_DB_PASSWORD=postgres
python main.py
```

#### UP2

```bash
export FOUR_NODE_ROLE=edge
export FOUR_ENABLED_SENSORS=radar_2,ble_2
export FOUR_MQTT_HOST=192.168.138.1
export FOUR_MQTT_PORT=1883
export FOUR_INGEST_ENABLE_DB=0
python main.py
```

#### PC

Otevri:

```text
http://192.168.137.2:8000
```

### Varianta C - samostatne procesy

Ingestion:

```powershell
python ingestion.py
```

Fusion:

```powershell
python fusion.py
```

Web/API:

```powershell
uvicorn app:app --host 0.0.0.0 --port 8000
```

## Testovaci Scenare

Ve slozce `test_soubory` je sada simulaci. Tyto scenare:

- publikuji synteticka radarova data do `sensors/raw/radar_*`
- publikuji synteticka BLE data do `sensors/raw/ble_*`
- ukladaji stejne typy dat do DB
- pouzivaji stejnou geometrii senzoru jako ostry system

### Dostupne Scenare

| File | Scenario |
| --- | --- |
| `test_01_linear_pass.py` | linearni pruchod |
| `test_02_circular_motion.py` | kruhovy pohyb |
| `test_03_stop_and_go.py` | stop and go |
| `test_04_x_pattern.py` | krizeni drah |
| `test_05_zigzag_speed_change.py` | zig-zag a zmeny rychlosti |
| `test_06_occlusion.py` | occlusion a dropout |
| `test_07_noise_injection.py` | vice urovni sumu |
| `test_08_id_recovery.py` | navrat po vypadku |
| `test_09_vertical_motion.py` | vertikalni pohyb |
| `test_10_spiral_motion.py` | 3D spirala |
| `test_11_detached_tag.py` | odlozeny BLE tag |
| `test_12_shift_change_crowd.py` | shluk vice lidi |
| `test_13_forklift_brake.py` | rychly prujezd a prudke zastaveni |

### Spusteni Simulace

Spoustej z nadrazene slozky tak, aby importy `Four.*` fungovaly:

```powershell
cd ..
python -m Four.test_soubory.test_01_linear_pass
```

Pro simulace musi bezet:

- MQTT broker
- PostgreSQL
- fusion vrstva
- webova vrstva, pokud chces videt dashboard

## Uzitecne Prikazy

Pocet radku a velikost tabulek:

```powershell
python db_stats.py
```

Kontrola rout:

```bash
ip route
```

Kontrola IP forwarding:

```bash
sysctl net.ipv4.ip_forward
```

Kontrola NAT pravidel:

```bash
iptables -t nat -L -n -v
```

## Doporucene Persistence Nastaveni

Pro stabilni deployment:

- sit pres `netplan`
- `sysctl` pro `net.ipv4.ip_forward=1`
- ulozena `iptables` pravidla
- persistentni Windows route s `route -p`
- auto-activation `venv` pri vstupu do projektove slozky

## Zname Omezeni

- `fusion.py` zatim nepouziva `kalman_filter.py`
- fusion heuristika je ladena pro malou mistnost cca `3 x 3 m`
- `docker-compose.yml` ve workspace nepokryva MQTT broker
- `main.py` v roli `central` spousti i ingestion, coz neni idealni pokud central
  nema fyzicky pripojene lokalni senzory
- projekt nema migrace, autentizaci ani service management pres `systemd`

## Budouci Rozsireni

- zapojeni plneho trackeru nad `kalman_filter.py`
- firewall rules a omezeni pristupu
- DHCP server na `UP2`, pokud bude sit vice autonomni
- `systemd` service pro jednotlive casti
- monitoring a watchdog
- VPN pristup do site

## Shrnuti

`Four` je prakticky prototyp distribuovaneho senzoroveho systemu:

- `UP2` sbira cast senzorovych dat a dela edge ingestion
- `UP1` slouzi jako centralni fusion a dashboard node
- PC funguje jako management konzole a klient dashboardu
- data tecou pres MQTT, ukladaji se do PostgreSQL a zobrazuji se pres WebSocket

Sitova cast z obrazku a realny kod projektu si odpovidaji: `UP1` je centralni
uzel s fusion vrstvou a `UP2` je edge node / gateway, ktery muze poskytovat
pripojeni i internetu cele experimentni siti.
