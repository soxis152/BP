"""Centralni konfigurace projektu.

Vychozi hodnoty odpovidaji aktualnimu laboratornimu nastaveni. Vsechny dulezite
hodnoty ale jde prepsat pres environment variables s prefixem `FOUR_`, aby se
kvuli jinemu pocitaci, portu nebo databazi nemusel menit zdrojovy kod.
"""

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def env_int(name, default):
    value = os.getenv(name)
    return default if value in (None, "") else int(value)


def env_float(name, default):
    value = os.getenv(name)
    return default if value in (None, "") else float(value)


def env_path(name, default):
    value = os.getenv(name)
    return Path(default if value in (None, "") else value)


MQTT_HOST = os.getenv("FOUR_MQTT_HOST", "127.0.0.1")
MQTT_PORT = env_int("FOUR_MQTT_PORT", 1883)

API_HOST = os.getenv("FOUR_API_HOST", "127.0.0.1")
API_PORT = env_int("FOUR_API_PORT", 8000)

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

RADAR_CONFIG_FILE = env_path(
    "FOUR_RADAR_CONFIG_FILE",
    BASE_DIR / "radar" / "tdm" / "AWR294X_profile_2025_11_07T16_27_59_226 copy2.cfg",
)

BLE_CONFIGS = [
    {
        "id": "ble_1",
        "port": os.getenv("FOUR_BLE_1_PORT", "COM38"),
        "baud": env_int("FOUR_BLE_1_BAUD", 115200),
        "pos_x": env_float("FOUR_BLE_1_POS_X", 1.5),
        "pos_y": env_float("FOUR_BLE_1_POS_Y", 0.0),
        "pos_z": env_float("FOUR_BLE_1_POS_Z", 0.8),
        "rotation": env_float("FOUR_BLE_1_ROTATION", 90),
    },
    {
        "id": "ble_2",
        "port": os.getenv("FOUR_BLE_2_PORT", "COM17"),
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
        "cfg_port": os.getenv("FOUR_RADAR_1_CFG_PORT", "COM13"),
        "dat_port": os.getenv("FOUR_RADAR_1_DAT_PORT", "COM14"),
        "pos_x": env_float("FOUR_RADAR_1_POS_X", 1.5),
        "pos_y": env_float("FOUR_RADAR_1_POS_Y", 0.0),
        "pos_z": env_float("FOUR_RADAR_1_POS_Z", 0.8),
        "rotation": env_float("FOUR_RADAR_1_ROTATION", 0),
    },
    {
        "id": "radar_2",
        "cfg_port": os.getenv("FOUR_RADAR_2_CFG_PORT", "COM11"),
        "dat_port": os.getenv("FOUR_RADAR_2_DAT_PORT", "COM12"),
        "pos_x": env_float("FOUR_RADAR_2_POS_X", 0.0),
        "pos_y": env_float("FOUR_RADAR_2_POS_Y", 1.5),
        "pos_z": env_float("FOUR_RADAR_2_POS_Z", 0.8),
        "rotation": env_float("FOUR_RADAR_2_ROTATION", -90),
    },
]
