import paho.mqtt.client as mqtt
import json
import threading
import time
import math
from pathlib import Path
import serial
import re
import asyncio  # Přidán import asyncio

from queue import Queue

# Změněn import - používáme pouze asynchronní db_handler
from db_handler import db_handler
from radar.radar_interface import RadarInterface

# Globální fronta pro předávání dat mezi senzory a databázovým workerem
db_queue = Queue()

# Regulární výraz pro parsování UUDF zpráv z u-blox BLE kotev
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
        "pos_x": 2.5, "pos_y": 0.0, "pos_z": 0.7,
        "rotation": 90
    },
    {
        "id": "ble_2",
        "port": "COM34",
        "baud": 115200,
        "pos_x": 0.0, "pos_y": 3.0, "pos_z": 0.7,
        "rotation": 0
    }
]

BASE_DIR = Path(__file__).resolve().parent
RADAR_CONFIG_FILE = BASE_DIR / "radar" / "tdm" / "AWR294X_profile_2025_11_07T16_27_59_226 copy1.cfg"

RADAR_CONFIGS = [
    {
        "id": "radar_1",
        "cfg_port": "COM11",
        "dat_port": "COM12",
        "pos_x": 1.5, "pos_y": 0.0, "pos_z": 0.7,
        "rotation": 90
    },
    {
        "id": "radar_2",
        "cfg_port": "COM13",
        "dat_port": "COM14",
        "pos_x": 0.0, "pos_y": 1.5, "pos_z": 0.7,
        "rotation": 0
    }
]


# ==========================================
# --- POMOCNÉ FUNKCE ---
# ==========================================

def send_radar_config(cfg):
    try:
        with serial.Serial(cfg["cfg_port"], 115200, timeout=1) as ser:
            with open(RADAR_CONFIG_FILE, 'r') as f:
                for line in f:
                    cmd = line.strip()
                    if cmd and not cmd.startswith('%'):
                        ser.write((cmd + '\n').encode())
                        time.sleep(0.05)
            print(f"Radar {cfg['id']}: Konfigurace úspěšně odeslána.")
    except Exception as e:
        print(f"Radar {cfg['id']}: Chyba konfigurace: {e}")


def transform_to_global(x_loc, y_loc, z_loc, cfg):
    angle_rad = math.radians(cfg["rotation"])
    x_glob = x_loc * math.cos(angle_rad) - y_loc * math.sin(angle_rad)
    y_glob = x_loc * math.sin(angle_rad) + y_loc * math.cos(angle_rad)
    return x_glob + cfg["pos_x"], y_glob + cfg["pos_y"], z_loc + cfg["pos_z"]


# ==========================================
# --- WORKERY ---
# ==========================================

def db_worker():
    """Vlákno, které vybírá data z fronty a zapisuje je do asynchronní DB."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # 1. Vytvoříme spojení do DB (Connection Pool)
    loop.run_until_complete(db_handler.connect())

    # 2. NOVÉ: Asynchronní vytvoření tabulek (nahrazuje starý init_db)
    loop.run_until_complete(db_handler.init_tables())

    buffers = {"ble_1": [], "ble_2": [], "radar_1": [], "radar_2": []}
    print("DB Worker: Připraven k asynchronnímu zápisu.")

    while True:
        table_name, data = db_queue.get()

        if table_name in buffers:
            buffers[table_name].append(data)

            # Zápis při 50 kusech nebo když je prázdná fronta
            if len(buffers[table_name]) >= 50 or db_queue.empty():
                try:
                    loop.run_until_complete(db_handler.insert_batch(table_name, buffers[table_name]))
                    buffers[table_name].clear()
                except Exception as e:
                    print(f"DB Error ({table_name}): {e}")

        db_queue.task_done()


def radar_worker(cfg):
    send_radar_config(cfg)

    # Připojení k MQTT brokeru
    mqtt_client = mqtt.Client(client_id=f"ingest_{cfg['id']}")
    mqtt_client.connect("127.0.0.1", 1883)
    mqtt_client.loop_start()  # Stará se o automatický reconnect na pozadí

    while True:
        try:
            radar = RadarInterface(port=cfg["dat_port"], baudrate=921600)
            print(f"Radar {cfg['id']}: Připojen.")

            while True:
                raw_data = radar.read_data()
                if raw_data:
                    parsed = radar.parse_frame(raw_data)
                    if parsed and len(parsed) >= 11:
                        for i in range(len(parsed[7])):
                            x_l, y_l, z_l = parsed[7][i], parsed[8][i], parsed[9][i]
                            snr = parsed[14][i]
                            x_g, y_g, z_g = transform_to_global(x_l, y_l, z_l, cfg)

                            # 1. Zápis do MQTT (pro real-time fúzi)
                            payload = {"timestamp": time.time(), "x": x_g, "y": y_g, "z": z_g, "snr": snr}
                            mqtt_client.publish(f"sensors/raw/{cfg['id']}", json.dumps(payload))

                            # 2. Zápis do DB fronty (pro historii)
                            db_queue.put((cfg["id"], (time.time(), x_g, y_g, z_g, snr)))
        except Exception as e:
            print(f"Radar {cfg['id']} Error: {e}. Restart za 5s...")
            time.sleep(5)


def ble_worker(cfg):
    mqtt_client = mqtt.Client(client_id=f"ingest_{cfg['id']}")
    mqtt_client.connect("127.0.0.1", 1883)
    mqtt_client.loop_start()

    while True:
        try:
            with serial.Serial(cfg["port"], cfg["baud"], timeout=1) as ser:
                print(f"BLE {cfg['id']}: Připojen.")
                while True:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    match = AZIMUTH_PATTERN.match(line)
                    if match:
                        tag_id, rssi, azimuth = match.group(1), int(match.group(2)), int(match.group(3))

                        # 1. Zápis do MQTT
                        payload = {"timestamp": time.time(), "tag_id": tag_id, "rssi": rssi, "azimuth": azimuth}
                        mqtt_client.publish(f"sensors/raw/{cfg['id']}", json.dumps(payload))

                        # 2. Zápis do DB fronty
                        db_queue.put((cfg["id"], (time.time(), tag_id, rssi, azimuth)))
        except Exception as e:
            print(f"BLE {cfg['id']} Error: {e}. Restart za 5s...")
            time.sleep(5)


# ==========================================
# --- HLAVNÍ SPOUŠTĚNÍ ---
# ==========================================

if __name__ == "__main__":

    # Spuštění workeru pro zápis dat na pozadí
    threading.Thread(target=db_worker, daemon=True).start()

    # Spuštění obsluhy pro všechny radary
    for cfg in RADAR_CONFIGS:
        threading.Thread(target=radar_worker, args=(cfg,), daemon=True).start()

    # Spuštění obsluhy pro všechny BLE kotvy
    for cfg in BLE_CONFIGS:
        threading.Thread(target=ble_worker, args=(cfg,), daemon=True).start()

    print("Sběr dat spuštěn. Ukončete pomocí Ctrl+C.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nUkončuji systém...")