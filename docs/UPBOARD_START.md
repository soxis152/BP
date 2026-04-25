# Start pro 2x UP Board

## Centralni UP board

Na centralnim nodu musi bezet:

- MQTT broker
- PostgreSQL
- `main.py` v roli `central`

Skripty jsou doporuceny wrapper kolem `python main.py`. Muzes spoustet i `python main.py` rucne, ale jen kdyz predem nastavis stejne `FOUR_*` promenne jako skript.

Spusteni:

```bash
cd /cesta/k/Four
chmod +x scripts/start_up_central.sh
./scripts/start_up_central.sh
```

Vychozi chovani:

- `FOUR_NODE_ROLE=central`
- `FOUR_ENABLED_SENSORS=radar_1,ble_1`
- `FOUR_INGEST_ENABLE_DB=1`
- `FOUR_API_HOST=0.0.0.0`
- `FOUR_MQTT_HOST=127.0.0.1`
- `FOUR_DB_HOST=127.0.0.1`
- `FOUR_DB_PORT=5432`

Kdyz chces prepsat porty nebo IP:

```bash
export FOUR_RADAR_1_CFG_PORT=/dev/ttyACM0
export FOUR_RADAR_1_DAT_PORT=/dev/ttyACM1
export FOUR_BLE_1_PORT=/dev/ttyUSB2
./scripts/start_up_central.sh
```

Pred prvnim startem si na centralu over skutecne porty senzoru, napriklad:

```bash
ls /dev/ttyACM* /dev/ttyUSB*
```

## Edge UP board

Na edge nodu bezi jen ingestion jeho lokalnich senzoru. Nepousti fusion ani API.

Na edge se nepripojuje PostgreSQL. Posila jen raw data do MQTT na centralnim nodu.

Spusteni:

```bash
cd /cesta/k/Four
chmod +x scripts/start_up_edge.sh
./scripts/start_up_edge.sh 192.168.1.10
```

Kde `192.168.137.2` je IP centralniho UP boardu s MQTT brokerem.

Vychozi chovani:

- `FOUR_NODE_ROLE=edge`
- `FOUR_ENABLED_SENSORS=radar_2,ble_2`
- `FOUR_INGEST_ENABLE_DB=0`
- `FOUR_MQTT_HOST=<IP centralu>`

Pozor: vychozi Linux porty pro `radar_2` a `ble_2` v `config.py` jsou placeholdery. Na edge je skoro vzdy potreba je prepsat rucne.

Kdyz chces prepsat porty:

```bash
export FOUR_RADAR_2_CFG_PORT=/dev/ttyACM0
export FOUR_RADAR_2_DAT_PORT=/dev/ttyACM1
export FOUR_BLE_2_PORT=/dev/ttyUSB2
./scripts/start_up_edge.sh 192.168.137.2
```

Pred prvnim startem si na edge over skutecne porty senzoru, napriklad:

```bash
ls /dev/ttyACM* /dev/ttyUSB*
```

## Recorder a testy

`record_experiment.py` spoustej na centralnim nodu, protoze jen tam jsou pohromade:

- raw data z obou UP boardu pres MQTT
- fused vystup

Priklad:

```bash
python -m Four.experiment_tools.record_experiment --label "test_01"
```

Prakticky dopad:

- pro `raw.ndjson` a `fused.ndjson` to staci, protoze recorder na centralu vidi cely MQTT provoz z obou boardu
- zmena `--label` prepne `run_id` jen na nodu, ktery vidi stejny `ACTIVE_RUN_ID_FILE`
- pokud sbiras serial diagnostiku i na edge, ta se bez dalsi synchronizace na novy label sama neprepne

## Co otestovat zitra

1. Na centralu spustit `./scripts/start_up_central.sh`
2. Na edge spustit `./scripts/start_up_edge.sh <IP_centralu>`
3. Overit skutecne `/dev/ttyACM*` a `/dev/ttyUSB*` na obou nodech a pripadne exportovat porty rucne
4. Overit, ze central vidi `sensors/raw/radar_1`, `sensors/raw/radar_2`, `sensors/raw/ble_1`, `sensors/raw/ble_2`
5. Overit, ze se na centralu generuje `sensors/fused`
6. Spustit recorder jen na centralu
