"""Sberna vrstva pro fyzicke senzory.

Modul cte data z radarovych a BLE seriovych portu, prevadi radarove body do
globalni mapy mistnosti, publikuje raw mereni do MQTT a uklada je do DB.

Ingestion zamerne nic nefuzuje a neprirazuje identitu. Jeho vystup ma byt co
nejbliz raw mereni, aby se chyby v hardwaru, DB, MQTT a fusion vrstve daly
ladit oddelene.
"""

import asyncio
import json
import math
import re
import threading
import time
from queue import Queue

import paho.mqtt.client as mqtt
import serial

try:
    from config import BLE_CONFIGS, DB_BATCH_SIZE, MQTT_HOST, MQTT_PORT, RADAR_CONFIG_FILE, RADAR_CONFIGS, RUN_ID
    from db_handler import db_handler
    from radar.radar_interface import RadarInterface
except ImportError:
    from .config import BLE_CONFIGS, DB_BATCH_SIZE, MQTT_HOST, MQTT_PORT, RADAR_CONFIG_FILE, RADAR_CONFIGS, RUN_ID
    from .db_handler import db_handler
    from .radar.radar_interface import RadarInterface


db_queue = Queue()

AZIMUTH_PATTERN = re.compile(
    r'\+UUDF:([0-9A-Fa-f]{12}),(-?\d+),(-?\d+),(-?\d+),(\d+),(\d+),"([0-9A-Fa-f]{12})","",(\d+),(\d+)'
)

# Lehky gate pred publikaci do MQTT. Cilem je zahodit zjevne odrazy mimo
# sledovanou 3x3m oblast, ne delat finalni filtraci objektu.
INGEST_GATE_X_MIN = -0.5
INGEST_GATE_X_MAX = 3.5
INGEST_GATE_Y_MIN = -0.5
INGEST_GATE_Y_MAX = 3.5
INGEST_GATE_Z_MIN = 0.0
INGEST_GATE_Z_MAX = 2.5

RADAR_CONFIG_COMMAND_DELAY_SECONDS = 0.12
RADAR_CONFIG_CONTROL_DELAY_SECONDS = 0.50


def send_radar_config(cfg):
    """Posle do radaru konfiguracni profil."""
    try:
        print(f"Radar {cfg['id']}: Posilam konfiguraci na {cfg['cfg_port']}...")
        with serial.Serial(cfg["cfg_port"], 115200, timeout=1) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            with open(RADAR_CONFIG_FILE, "r") as file_handle:
                for line in file_handle:
                    cmd = line.strip()
                    if cmd and not cmd.startswith("%"):
                        ser.write((cmd + "\n").encode())
                        delay = (
                            RADAR_CONFIG_CONTROL_DELAY_SECONDS
                            if cmd in {"sensorStop", "flushCfg", "sensorStart"}
                            else RADAR_CONFIG_COMMAND_DELAY_SECONDS
                        )
                        time.sleep(delay)
            print(f"Radar {cfg['id']}: Konfigurace uspesne odeslana.")
            return True
    except Exception as exc:
        print(f"Radar {cfg['id']}: Chyba konfigurace: {exc}")
        return False


def transform_to_global(x_loc, y_loc, z_loc, cfg):
    """Prevede lokalni radarove souradnice do globalni mapy mistnosti."""
    angle_rad = math.radians(cfg["rotation"])
    x_glob = x_loc * math.cos(angle_rad) - y_loc * math.sin(angle_rad)
    y_glob = x_loc * math.sin(angle_rad) + y_loc * math.cos(angle_rad)
    return x_glob + cfg["pos_x"], y_glob + cfg["pos_y"], z_loc + cfg["pos_z"]


def db_worker():
    """Zapisuje data z fronty do PostgreSQL po davkach."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(db_handler.connect())
    loop.run_until_complete(db_handler.init_tables())

    buffers = {"ble_1": [], "ble_2": [], "radar_1": [], "radar_2": [], "fused_data": []}
    print("DB Worker: Pripraven k asynchronnimu zapisu.")

    while True:
        table_name, data = db_queue.get()

        if table_name in buffers:
            buffers[table_name].append(data)

            if len(buffers[table_name]) >= DB_BATCH_SIZE or db_queue.empty():
                try:
                    loop.run_until_complete(db_handler.insert_batch(table_name, buffers[table_name]))
                    buffers[table_name].clear()
                except Exception as exc:
                    print(f"DB Error ({table_name}): {exc}")

        db_queue.task_done()


def radar_worker(cfg):
    """Cte jeden radar, publikuje jeho body do MQTT a uklada je do DB."""
    while not send_radar_config(cfg):
        time.sleep(5)

    mqtt_client = mqtt.Client(client_id=f"ingest_{cfg['id']}")
    mqtt_client.connect(MQTT_HOST, MQTT_PORT)
    mqtt_client.loop_start()

    while True:
        try:
            radar = RadarInterface(port=cfg["dat_port"], baudrate=921600)
            print(f"Radar {cfg['id']}: Pripojen.")

            while True:
                raw_data = radar.read_data()
                if not raw_data:
                    continue

                parsed = radar.parse_frame(raw_data)
                if not parsed or len(parsed) < 11:
                    continue

                detections_for_print = []
                for index in range(len(parsed[7])):
                    x_l, y_l, z_l = parsed[7][index], parsed[8][index], parsed[9][index]
                    doppler = parsed[10][index]
                    snr = parsed[14][index]

                    x_g, y_g, z_g = transform_to_global(x_l, y_l, z_l, cfg)

                    if not (INGEST_GATE_X_MIN <= x_g <= INGEST_GATE_X_MAX):
                        continue
                    if not (INGEST_GATE_Y_MIN <= y_g <= INGEST_GATE_Y_MAX):
                        continue
                    if not (INGEST_GATE_Z_MIN <= z_g <= INGEST_GATE_Z_MAX):
                        continue

                    detections_for_print.append((x_g, y_g, z_g, snr, doppler))

                    payload = {
                        "timestamp": time.time(),
                        "x": x_g,
                        "y": y_g,
                        "z": z_g,
                        "snr": snr,
                        "doppler": doppler,
                    }
                    mqtt_client.publish(f"sensors/raw/{cfg['id']}", json.dumps(payload))
                    db_queue.put((cfg["id"], (RUN_ID, time.time(), x_g, y_g, z_g, snr, doppler)))

                if detections_for_print:
                    formatted = ", ".join(
                        f"(x={x:.2f}, y={y:.2f}, z={z:.2f}, dop={d:.2f}, snr={s})"
                        for x, y, z, s, d in detections_for_print
                    )
                    print(f"{cfg['id']} vidi: {formatted}")

        except Exception as exc:
            print(f"Radar {cfg['id']} Error: {exc}. Restart za 5s...")
            time.sleep(5)


def ble_worker(cfg):
    """Cte jednu BLE kotvu, publikuje azimuty do MQTT a uklada je do DB."""
    mqtt_client = mqtt.Client(client_id=f"ingest_{cfg['id']}")
    mqtt_client.connect(MQTT_HOST, MQTT_PORT)
    mqtt_client.loop_start()

    while True:
        try:
            with serial.Serial(cfg["port"], cfg["baud"], timeout=1) as ser:
                print(f"BLE {cfg['id']}: Pripojen.")

                while True:
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                    match = AZIMUTH_PATTERN.match(line)
                    if not match:
                        continue

                    tag_id = match.group(1).upper()
                    rssi = int(match.group(2))
                    azimuth = int(match.group(3))
                    elevation = int(match.group(4))
                    timestamp = time.time()

                    payload = {
                        "timestamp": timestamp,
                        "tag_id": tag_id,
                        "rssi": rssi,
                        "azimuth": azimuth,
                        "elevation": elevation,
                    }
                    mqtt_client.publish(f"sensors/raw/{cfg['id']}", json.dumps(payload))
                    db_queue.put((cfg["id"], (RUN_ID, timestamp, tag_id, rssi, azimuth, elevation)))

        except Exception as exc:
            print(f"BLE {cfg['id']} Error: {exc}. Restart za 5s...")
            time.sleep(5)


if __name__ == "__main__":
    threading.Thread(target=db_worker, daemon=True).start()

    for cfg in RADAR_CONFIGS:
        threading.Thread(target=radar_worker, args=(cfg,), daemon=True).start()

    for cfg in BLE_CONFIGS:
        threading.Thread(target=ble_worker, args=(cfg,), daemon=True).start()

    print("Sber dat spusten. Ukoncete pomoci Ctrl+C.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nUkoncuji system...")
