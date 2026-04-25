"""Centralni konfigurace projektu.

Vychozi hodnoty odpovidaji aktualnimu laboratornimu nastaveni. Vsechny dulezite
hodnoty ale jde prepsat pres environment variables s prefixem `FOUR_`, aby se
kvuli jinemu pocitaci, portu nebo databazi nemusel menit zdrojovy kod.
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


def env_bool(name, default):
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_path(name, default):
    value = os.getenv(name)
    return Path(default if value in (None, "") else value)


def env_csv_set(name, default_items):
    value = os.getenv(name)
    raw_items = default_items if value in (None, "") else value.split(",")
    return {item.strip() for item in raw_items if item.strip()}


def platform_default(windows_value, non_windows_value):
    return windows_value if os.name == "nt" else non_windows_value


MQTT_HOST = os.getenv("FOUR_MQTT_HOST", "127.0.0.1")
MQTT_PORT = env_int("FOUR_MQTT_PORT", 1883)

API_HOST = os.getenv("FOUR_API_HOST", platform_default("127.0.0.1", "0.0.0.0"))
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
RUN_ID = os.getenv("FOUR_RUN_ID", DEFAULT_RUN_ID)
NODE_ROLE = os.getenv("FOUR_NODE_ROLE", "all").strip().lower()
ENABLED_SENSORS = env_csv_set(
    "FOUR_ENABLED_SENSORS",
    ("radar_1", "radar_2", "ble_1", "ble_2"),
)
INGEST_ENABLE_DB = env_bool("FOUR_INGEST_ENABLE_DB", True)
DEFAULT_EXPERIMENT_LABEL = os.getenv("FOUR_EXPERIMENT_LABEL", "laborator_02")
ACTIVE_RUN_ID_FILE = env_path("FOUR_ACTIVE_RUN_ID_FILE", BASE_DIR / ".active_run_id")
CAPTURE_RAW_SERIAL = env_bool("FOUR_CAPTURE_RAW_SERIAL", True)
DIAGNOSTIC_CAPTURE_DIR = env_path(
    "FOUR_DIAGNOSTIC_CAPTURE_DIR",
    BASE_DIR / "runs" / "diagnostic",
)

RADAR_CONFIG_FILE = env_path(
    "FOUR_RADAR_CONFIG_FILE",
    BASE_DIR / "radar" / "tdm" / "AWR294X_profile_2025_11_07T16_27_59_226 copy2.cfg",
)
RADAR_CFG_BAUD = env_int("FOUR_RADAR_CFG_BAUD", 115200)
RADAR_DATA_BAUD = env_int("FOUR_RADAR_DATA_BAUD", 921600)

BLE_CONFIGS = [
    {
        "id": "ble_1",
        "port": os.getenv("FOUR_BLE_1_PORT", platform_default("COM38", "/dev/ttyUSB2")),
        "baud": env_int("FOUR_BLE_1_BAUD", 115200),
        "pos_x": env_float("FOUR_BLE_1_POS_X", 1.5),
        "pos_y": env_float("FOUR_BLE_1_POS_Y", 0.0),
        "pos_z": env_float("FOUR_BLE_1_POS_Z", 0.8),
        "rotation": env_float("FOUR_BLE_1_ROTATION", 90),
    },
    {
        "id": "ble_2",
        "port": os.getenv("FOUR_BLE_2_PORT", platform_default("COM17", "/dev/ttyUSB99")),
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
        "cfg_port": os.getenv("FOUR_RADAR_1_CFG_PORT", platform_default("COM13", "/dev/ttyACM0")),
        "dat_port": os.getenv("FOUR_RADAR_1_DAT_PORT", platform_default("COM14", "/dev/ttyACM1")),
        "pos_x": env_float("FOUR_RADAR_1_POS_X", 1.5),
        "pos_y": env_float("FOUR_RADAR_1_POS_Y", 0.0),
        "pos_z": env_float("FOUR_RADAR_1_POS_Z", 0.8),
        "rotation": env_float("FOUR_RADAR_1_ROTATION", 0),
    },
    {
        "id": "radar_2",
        "cfg_port": os.getenv("FOUR_RADAR_2_CFG_PORT", platform_default("COM11", "/dev/ttyACM98")),
        "dat_port": os.getenv("FOUR_RADAR_2_DAT_PORT", platform_default("COM12", "/dev/ttyACM99")),
        "pos_x": env_float("FOUR_RADAR_2_POS_X", 0.0),
        "pos_y": env_float("FOUR_RADAR_2_POS_Y", 1.5),
        "pos_z": env_float("FOUR_RADAR_2_POS_Z", 0.8),
        "rotation": env_float("FOUR_RADAR_2_ROTATION", -90),
    },
]
