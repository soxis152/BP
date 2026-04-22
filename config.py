"""Centralni konfigurace projektu pro upboard1.

upboard1 funguje jako centralni node:
- bezi na nem ingestion pro radar_1 a ble_1
- bezi na nem MQTT broker
- bezi na nem PostgreSQL
- bezi na nem fusion
- bezi na nem API/dashboard
"""

import os
from pathlib import Path
from datetime import datetime


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_RUN_ID = datetime.now().strftime("run_%Y%m%d_%H%M%S")


def env_int(name, default):
    value = os.getenv(name)
    return default if value in (None, "") else int(value)


def env_float(name, default):
    value = os.getenv(name)
    return default if value in (None, "") else float(value)


def env_path(name, default):
    value = os.getenv(name)
    return Path(default if value in (None, "") else value)


# MQTT broker bezi lokalne na upboard1
MQTT_HOST = os.getenv("FOUR_MQTT_HOST", "127.0.0.1")
MQTT_PORT = env_int("FOUR_MQTT_PORT", 1883)

# API ma byt dostupne i z PC
API_HOST = os.getenv("FOUR_API_HOST", "0.0.0.0")
API_PORT = env_int("FOUR_API_PORT", 8000)

# DB bezi lokalne na upboard1
DB_CONFIG = {
    "user": os.getenv("FOUR_DB_USER", "postgres"),
    "password": os.getenv("FOUR_DB_PASSWORD", "postgres"),
    "database": os.getenv("FOUR_DB_NAME", "sensor_data"),
    "host": os.getenv("FOUR_DB_HOST", "127.0.0.1"),
    "port": env_int("FOUR_DB_PORT", 5432),
    "min_size": env_int("FOUR_DB_POOL_MIN_SIZE", 1),
    "max_size": env_int("FOUR_DB_POOL_MAX_SIZE", 5),
    "command_timeout": env_float("FOUR_DB_COMMAND_TIMEOUT", 60.0),
}
DB_SCHEMA = os.getenv("FOUR_DB_SCHEMA", "public")
DB_BATCH_SIZE = env_int("FOUR_DB_BATCH_SIZE", 100)
DB_FLUSH_SECONDS = env_float("FOUR_DB_FLUSH_SECONDS", 1.0)
RUN_ID = os.getenv("FOUR_RUN_ID", DEFAULT_RUN_ID)

# upboard1 = centralni node
NODE_ROLE = os.getenv("FOUR_NODE_ROLE", "central").strip().lower()

# Na upboard1 bezi jen prvni BLE kotva a prvni radar
ENABLED_SENSORS = {
    sensor_id.strip()
    for sensor_id in os.getenv(
        "FOUR_ENABLED_SENSORS",
        "radar_1,ble_1",
    ).split(",")
    if sensor_id.strip()
}

# Raw DB zapis na upboard1 zapnuty
INGEST_ENABLE_DB = os.getenv("FOUR_INGEST_ENABLE_DB", "1").strip() == "1"

RADAR_CONFIG_FILE = env_path(
    "FOUR_RADAR_CONFIG_FILE",
    BASE_DIR / "radar" / "tdm" / "AWR294X_profile_2025_11_07T16_27_59_226 copy2.cfg",
)

BLE_CONFIGS = [
    {
        "id": "ble_1",
        "port": os.getenv("FOUR_BLE_1_PORT", "/dev/ttyUSB0"),
        "baud": env_int("FOUR_BLE_1_BAUD", 115200),
        "pos_x": env_float("FOUR_BLE_1_POS_X", 1.5),
        "pos_y": env_float("FOUR_BLE_1_POS_Y", 0.0),
        "pos_z": env_float("FOUR_BLE_1_POS_Z", 0.8),
        "rotation": env_float("FOUR_BLE_1_ROTATION", 90),
    },
    {
        "id": "ble_2",
        "port": os.getenv("FOUR_BLE_2_PORT", "/dev/ttyUSB99"),
        "baud": env_int("FOUR_BLE_2_BAUD", 115200),
        "pos_x": env_float("FOUR_BLE_2_POS_X", 0.0),
        "pos_y": env_float("FOUR_BLE_2_POS_Y", 1.5),
        "pos_z": env_float("FOUR_BLE_2_POS_Z", 0.8),
        "rotation": env_float("FOUR_BLE_2_ROTATION", 0),
    },
]

RADAR_CONFIGS = [
    {
        "id": "radar_1",
        "cfg_port": os.getenv("FOUR_RADAR_1_CFG_PORT", "/dev/ttyACM0"),
        "dat_port": os.getenv("FOUR_RADAR_1_DAT_PORT", "/dev/ttyACM1"),
        "pos_x": env_float("FOUR_RADAR_1_POS_X", 1.5),
        "pos_y": env_float("FOUR_RADAR_1_POS_Y", 0.0),
        "pos_z": env_float("FOUR_RADAR_1_POS_Z", 0.8),
        "rotation": env_float("FOUR_RADAR_1_ROTATION", 0),
    },
    {
        "id": "radar_2",
        "cfg_port": os.getenv("FOUR_RADAR_2_CFG_PORT", "/dev/ttyACM98"),
        "dat_port": os.getenv("FOUR_RADAR_2_DAT_PORT", "/dev/ttyACM99"),
        "pos_x": env_float("FOUR_RADAR_2_POS_X", 0.0),
        "pos_y": env_float("FOUR_RADAR_2_POS_Y", 1.5),
        "pos_z": env_float("FOUR_RADAR_2_POS_Z", 0.8),
        "rotation": env_float("FOUR_RADAR_2_ROTATION", -90),
    },
]