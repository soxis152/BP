# Four

Projekt pro sber, fuzi a vizualizaci dat z radaru a BLE kotev.

Datovy tok:

```text
radar/BLE senzory -> ingestion.py -> MQTT -> fusion.py -> MQTT -> app.py -> WebSocket -> index.html
```

## Pozadavky

- Python 3.11 nebo novejsi
- MQTT broker dostupny na `127.0.0.1:1883`
- PostgreSQL dostupny na `127.0.0.1:5432`
- Databaze `sensor_data`
- Databazovy uzivatel `postgres` s heslem `postgres`
- Pro ostry beh fyzicke senzory na COM portech nastavenych v `config.py`

Projekt aktualne pouziva lokalni konfiguraci v `config.py`, kterou lze prepsat pres environment variables. Hlavni mista:

- `config.py`: DB, MQTT, API, COM porty, pozice senzoru a cesta k radarovemu profilu
- `fusion.py`: parametry parovani/fuze

## Konfigurace

Vychozi konfigurace je v `config.py`. Hodnoty jde prepsat pres environment variables:

```powershell
$env:FOUR_MQTT_HOST = "127.0.0.1"
$env:FOUR_MQTT_PORT = "1883"
$env:FOUR_DB_HOST = "127.0.0.1"
$env:FOUR_DB_PORT = "5432"
$env:FOUR_DB_NAME = "sensor_data"
$env:FOUR_DB_USER = "postgres"
$env:FOUR_DB_PASSWORD = "postgres"
$env:FOUR_DB_SCHEMA = "public"
$env:FOUR_API_HOST = "127.0.0.1"
$env:FOUR_API_PORT = "8000"
$env:FOUR_RUN_ID = "run_manual_001"
```

Porty senzoru:

```powershell
$env:FOUR_BLE_1_PORT = "COM38"
$env:FOUR_BLE_2_PORT = "COM17"
$env:FOUR_RADAR_1_CFG_PORT = "COM13"
$env:FOUR_RADAR_1_DAT_PORT = "COM14"
$env:FOUR_RADAR_2_CFG_PORT = "COM11"
$env:FOUR_RADAR_2_DAT_PORT = "COM12"
```

Cestu k radarovemu profilu lze prepsat pres:

```powershell
$env:FOUR_RADAR_CONFIG_FILE = "C:\path\to\profile.cfg"
```

Poznamka k radarum:

- `ingestion.py` pri startu sam posila profil do obou radaru pres jejich `cfg_port`.
- Pred `sensorStart` automaticky doplni prikaz `configDataPort 921600 0`, takze datovy UART neni potreba predem rucne rozbihat pres `radar/rad.py`.
- `radar/rad.py` zustava jako pomocny diagnosticky skript pro rucni oziveni jednoho radaru a jednoduche zobrazeni bodu.

## Instalace

Z korenove slozky projektu:

```powershell
cd C:\Users\kabup\OneDrive\Plocha\BP_\KÓD\Four
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## PostgreSQL pres Docker

V koreni workspace je `docker-compose.yml`, ale jeho vychozi hodnoty neodpovidaji aplikaci ve `Four`. Pokud ho chces pouzit bez uprav `config.py`, spust ho z korene repozitare s temito promennymi:

```powershell
cd C:\Users\kabup\OneDrive\Plocha\BP_\KÓD
$env:POSTGRES_DB = "sensor_data"
$env:POSTGRES_USER = "postgres"
$env:POSTGRES_PASSWORD = "postgres"
$env:POSTGRES_PORT = "5432"
docker compose up -d
```

Tenhle `docker-compose.yml` zveda jen PostgreSQL. MQTT broker je potreba spustit zvlast.

## Databaze

Aplikace ocekava databazi `sensor_data`. Tabulky a indexy se vytvori automaticky pri startu DB workeru.

Priklad vytvoreni databaze pres `psql`:

```powershell
psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE sensor_data;"
```

Pokud databaze uz existuje, tento krok neni potreba.

## MQTT

System ocekava MQTT broker na `127.0.0.1:1883`.

Pouzivane topicy:

```text
sensors/raw/radar_1
sensors/raw/radar_2
sensors/raw/ble_1
sensors/raw/ble_2
sensors/fused
```

`ingestion.py` publikuje syrova data do `sensors/raw/#`. `fusion.py` je cte, vytvori fused snapshot a publikuje ho do `sensors/fused`. `app.py` fused data preposila pres WebSocket dashboardu.

## Spusteni ostreho behu

Pred spustenim musi bezet PostgreSQL a MQTT broker. Take musi odpovidat COM porty a cesta k radarovemu profilu v `config.py` nebo v environment variables `FOUR_*`.

```powershell
cd C:\Users\kabup\OneDrive\Plocha\BP_\KÓD\Four
.\.venv\Scripts\Activate.ps1
python main.py
```

Dashboard potom otevri v prohlizeci:

```text
http://127.0.0.1:8000
```

`main.py` spousti tri casti v jednom procesu:

- ingestion worker pro radar/BLE vstupy a zapis do DB
- fusion loop pro clustering a parovani radar/BLE dat
- FastAPI server s dashboardem

Prakticky dopad:

- pokud nebezi MQTT broker, ingestion a fusion se nepripoji
- pokud nebezi PostgreSQL, spadne DB zapis v ingestion vrstve a `app.py` se pri startu nepripoji
- pokud neodpovidaji COM porty, radar/BLE workery se budou stale pokouset o reconnect

## Samostatne spusteni casti

Fusion:

```powershell
python fusion.py
```

Web/API:

```powershell
uvicorn app:app --host 127.0.0.1 --port 8000
```

Poznamka: i samostatne `app.py` potrebuje pri startu dostupnou databazi, protoze v `lifespan` vytvari `asyncpg` pool.

Ingestion:

```powershell
python ingestion.py
```

## Testovaci scenare

Ve slozce `test_soubory` jsou simulacni scenare, ktere generuji synteticka radarova a BLE mereni a posilaji je do stejneho MQTT rozhrani jako ostry system.

Aktualni scenare jsou popsane v `test_soubory/Popis_testu.md`.

Testovaci moduly aktualne importuji balicek jako `Four...`, coz odpovida aktualnimu nazvu adresare v tomto workspace. Pri presunu projektu do jine slozky je potreba zachovat stejny nazev balicku, nebo importy sjednotit.

Priklad spusteni prvniho scenare z nadrazene slozky projektu:

```powershell
cd C:\Users\kabup\OneDrive\Plocha\BP_\KÓD
python -m Four.test_soubory.test_01_linear_pass
```

Pro vyhodnoceni scenare musi bezet MQTT broker, PostgreSQL a idealne i `fusion.py` + `app.py`.

## Uzitecne pomocne skripty

Pocet radku a velikost tabulek v PostgreSQL:

```powershell
python db_stats.py
```

## Overeni syntaxe

Rychla kontrola, ze se vsechny Python soubory ve slozce `Four` parsuji. Spoustet z adresare `Four`:

```powershell
python -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in pathlib.Path('.').rglob('*.py')]; print('OK')"
```

## Zname technicke dluhy

- `kalman_filter.py` existuje, ale hlavni fusion vrstva ho zatim nepouziva.
