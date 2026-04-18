import asyncio
import json
import math
import re
import threading
import time
from pathlib import Path
from queue import Queue

import paho.mqtt.client as mqtt
import serial

from db_handler import db_handler
from radar.radar_interface import RadarInterface

# Tento modul je "sběrná vrstva" systému.
#
# Jeho úkol je čistě provozní:
# - číst syrová data z fyzických radarů a BLE kotev,
# - převést je do společné globální mapy místnosti,
# - poslat je do MQTT pro online fusion,
# - současně je uložit do DB pro historii a ladění.
#
# Zásadní vlastnost:
# ingestion nic nefúzuje a nic neidentifikuje.
# Pouze spolehlivě sbírá a distribuuje syrová měření.

# Fronta odděluje rychlé čtení senzorů od pomalejšího zápisu do databáze.
# Díky tomu radarový ani BLE worker nečekají na PostgreSQL.
db_queue = Queue()

# Parsování řádku z BLE kotev u-blox.
# Z celé zprávy nás zajímá hlavně:
# - tag_id,
# - RSSI,
# - azimut.
AZIMUTH_PATTERN = re.compile(
    r'\+UUDF:([0-9A-Fa-f]{12}),(-?\d+),(-?\d+),(-?\d+),(\d+),(\d+),"([0-9A-Fa-f]{12})","",(\d+),(\d+)'
)

# ==========================================
#  --- KONFIGURACE SYSTÉMU ---
# ==========================================

BLE_CONFIGS = [
    {
        "id": "ble_1",
        "port": "COM38",
        "baud": 115200,
        "pos_x": 1.5,
        "pos_y": 0.0,
        "pos_z": 0.8,
        "rotation": 90,
    },
    {
        "id": "ble_2",
        "port": "COM17",
        "baud": 115200,
        "pos_x": 0.0,
        "pos_y": 1.5,
        "pos_z": 0.8,
        "rotation": 0,
    },
]

BASE_DIR = Path(__file__).resolve().parent
RADAR_CONFIG_FILE = BASE_DIR / "radar" / "tdm" / "AWR294X_profile_2025_11_07T16_27_59_226 copy2.cfg"

RADAR_CONFIGS = [
    {
        "id": "radar_1",
        "cfg_port": "COM13",
        "dat_port": "COM14",
        "pos_x": 1.5,
        "pos_y": 0.0,
        "pos_z": 0.8,
        "rotation": 0,
    },
    {
        "id": "radar_2",
        "cfg_port": "COM11",
        "dat_port": "COM12",
        "pos_x": 0.0,
        "pos_y": 1.5,
        "pos_z": 0.8,
        "rotation": -90,
    },
]

# Lehký pre-gate před publikací do MQTT:
# cílem je zahodit očividné odrazy mimo sledovaný prostor, ale
# nenechat filtr příliš těsný (fusion si ještě dělá vlastní gate).
INGEST_GATE_X_MIN = -0.5
INGEST_GATE_X_MAX = 3.5
INGEST_GATE_Y_MIN = -0.5
INGEST_GATE_Y_MAX = 3.5
INGEST_GATE_Z_MIN = 0.0
INGEST_GATE_Z_MAX = 2.5

RADAR_CONFIG_COMMAND_DELAY_SECONDS = 0.12
RADAR_CONFIG_CONTROL_DELAY_SECONDS = 0.50


# ==========================================
# --- POMOCNÉ FUNKCE ---
# ==========================================

def send_radar_config(cfg):
    """Po startu pošle do radaru konfigurační profil."""
    try:
        print(f"Radar {cfg['id']}: Posílám konfiguraci na {cfg['cfg_port']}...")
        with serial.Serial(cfg["cfg_port"], 115200, timeout=1) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            with open(RADAR_CONFIG_FILE, "r") as file_handle:
                for line in file_handle:
                    cmd = line.strip()
                    if cmd and not cmd.startswith("%"):
                        ser.write((cmd + "\n").encode())
                        delay = RADAR_CONFIG_CONTROL_DELAY_SECONDS if cmd in {"sensorStop", "flushCfg", "sensorStart"} else RADAR_CONFIG_COMMAND_DELAY_SECONDS
                        time.sleep(delay)
            print(f"Radar {cfg['id']}: Konfigurace úspěšně odeslána.")
            return True
    except Exception as exc:
        print(f"Radar {cfg['id']}: Chyba konfigurace: {exc}")
        return False


def transform_to_global(x_loc, y_loc, z_loc, cfg):
    """Převede lokální radarové souřadnice do společné globální mapy místnosti."""
    angle_rad = math.radians(cfg["rotation"])
    x_glob = x_loc * math.cos(angle_rad) - y_loc * math.sin(angle_rad)
    y_glob = x_loc * math.sin(angle_rad) + y_loc * math.cos(angle_rad)
    return x_glob + cfg["pos_x"], y_glob + cfg["pos_y"], z_loc + cfg["pos_z"]


# ==========================================
# --- WORKERY ---
# ==========================================

def db_worker():
    """Samostatné vlákno pro asynchronní zápis do PostgreSQL."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(db_handler.connect())
    loop.run_until_complete(db_handler.init_tables())

    buffers = {"ble_1": [], "ble_2": [], "radar_1": [], "radar_2": [], "fused_data": []}
    print("DB Worker: Připraven k asynchronnímu zápisu.")

    while True:
        table_name, data = db_queue.get()

        if table_name in buffers:
            buffers[table_name].append(data)

            if len(buffers[table_name]) >= 50 or db_queue.empty():
                try:
                    loop.run_until_complete(db_handler.insert_batch(table_name, buffers[table_name]))
                    buffers[table_name].clear()
                except Exception as exc:
                    print(f"DB Error ({table_name}): {exc}")

        db_queue.task_done()


def radar_worker(cfg):
    while not send_radar_config(cfg):
        time.sleep(5)

    mqtt_client = mqtt.Client(client_id=f"ingest_{cfg['id']}")
    mqtt_client.connect("127.0.0.1", 1883)
    mqtt_client.loop_start()

    while True:
        try:
            radar = RadarInterface(port=cfg["dat_port"], baudrate=921600)
            print(f"Radar {cfg['id']}: Připojen.")

            while True:
                raw_data = radar.read_data()
                if not raw_data: continue
                parsed = radar.parse_frame(raw_data)
                if not parsed or len(parsed) < 11: continue

                detections_for_print = []
                for index in range(len(parsed[7])):
                    x_l, y_l, z_l = parsed[7][index], parsed[8][index], parsed[9][index]
                    doppler = parsed[10][index]
                    snr = parsed[14][index]

                    x_g, y_g, z_g = transform_to_global(x_l, y_l, z_l, cfg)

                    # Lehký pre-gate: odfiltrujeme zjevně mimo-prostorové body
                    # ještě před MQTT, aby fusion neřešila zbytečný odpad.
                    if not (INGEST_GATE_X_MIN <= x_g <= INGEST_GATE_X_MAX):
                        continue
                    if not (INGEST_GATE_Y_MIN <= y_g <= INGEST_GATE_Y_MAX):
                        continue
                    if not (INGEST_GATE_Z_MIN <= z_g <= INGEST_GATE_Z_MAX):
                        continue

                    detections_for_print.append((x_g, y_g, z_g, snr, doppler))

                    payload = {
                        "timestamp": time.time(),
                        "x": x_g, "y": y_g, "z": z_g,
                        "snr": snr, "doppler": doppler
                    }
                    mqtt_client.publish(f"sensors/raw/{cfg['id']}", json.dumps(payload))
                    db_queue.put((cfg["id"], (time.time(), x_g, y_g, z_g, snr, doppler)))

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
    """Obsluha jedné BLE kotvy."""
    mqtt_client = mqtt.Client(client_id=f"ingest_{cfg['id']}")
    mqtt_client.connect("127.0.0.1", 1883)
    mqtt_client.loop_start()

    while True:
        try:
            with serial.Serial(cfg["port"], cfg["baud"], timeout=1) as ser:
                print(f"BLE {cfg['id']}: Připojen.")

                while True:
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                    match = AZIMUTH_PATTERN.match(line)
                    if not match:
                        continue

                    tag_id = match.group(1)
                    rssi = int(match.group(2))
                    azimuth = int(match.group(3))

                    payload = {"timestamp": time.time(), "tag_id": tag_id, "rssi": rssi, "azimuth": azimuth}
                    mqtt_client.publish(f"sensors/raw/{cfg['id']}", json.dumps(payload))
                    db_queue.put((cfg["id"], (time.time(), tag_id, rssi, azimuth)))

        except Exception as exc:
            print(f"BLE {cfg['id']} Error: {exc}. Restart za 5s...")
            time.sleep(5)


# ==========================================
# --- HLAVNÍ SPOUŠTĚNÍ ---
# ==========================================

if __name__ == "__main__":
    threading.Thread(target=db_worker, daemon=True).start()

    for cfg in RADAR_CONFIGS:
        threading.Thread(target=radar_worker, args=(cfg,), daemon=True).start()

    for cfg in BLE_CONFIGS:
        threading.Thread(target=ble_worker, args=(cfg,), daemon=True).start()

    print("Sběr dat spuštěn. Ukončete pomocí Ctrl+C.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nUkončuji systém...")
