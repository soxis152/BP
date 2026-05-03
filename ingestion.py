"""Sberna vrstva pro fyzicke senzory.

Modul cte data z radarovych a BLE seriovych portu, prevadi radarove body do
globalni mapy mistnosti, publikuje raw mereni do MQTT a uklada je do DB.

Ingestion zamerne nic nefuzuje a neprirazuje identitu. Jeho vystup ma byt co
nejbliz raw mereni, aby se chyby v hardwaru, DB, MQTT a fusion vrstve daly
ladit oddelene.
"""

import asyncio
import base64
from datetime import datetime
import json
import math
import re
import threading
import time
from queue import Queue

import paho.mqtt.client as mqtt
import serial

try:
    from config import (
        BLE_CONFIGS,
        CAPTURE_RAW_SERIAL,
        DB_BATCH_SIZE,
        DIAGNOSTIC_CAPTURE_DIR,
        ENABLED_SENSORS,
        INGEST_ENABLE_DB,
        INGEST_GATE_X_MAX,
        INGEST_GATE_X_MIN,
        INGEST_GATE_Y_MAX,
        INGEST_GATE_Y_MIN,
        INGEST_GATE_Z_MAX,
        INGEST_GATE_Z_MIN,
        MQTT_HOST,
        MQTT_PORT,
        RADAR_BOOTSTRAP_CONFIG_FILE,
        RADAR_CFG_BAUD,
        RADAR_CONFIG_FILE,
        RADAR_CONFIGS,
        RADAR_DATA_BAUD,
    )
    from db_handler import db_handler
    from radar.radar_interface import RadarInterface
    from run_context import get_current_run_id
except ImportError:
    from .config import (
        BLE_CONFIGS,
        CAPTURE_RAW_SERIAL,
        DB_BATCH_SIZE,
        DIAGNOSTIC_CAPTURE_DIR,
        ENABLED_SENSORS,
        INGEST_ENABLE_DB,
        INGEST_GATE_X_MAX,
        INGEST_GATE_X_MIN,
        INGEST_GATE_Y_MAX,
        INGEST_GATE_Y_MIN,
        INGEST_GATE_Z_MAX,
        INGEST_GATE_Z_MIN,
        MQTT_HOST,
        MQTT_PORT,
        RADAR_BOOTSTRAP_CONFIG_FILE,
        RADAR_CFG_BAUD,
        RADAR_CONFIG_FILE,
        RADAR_CONFIGS,
        RADAR_DATA_BAUD,
    )
    from .db_handler import db_handler
    from .radar.radar_interface import RadarInterface
    from .run_context import get_current_run_id


db_queue = Queue()

AZIMUTH_PATTERN = re.compile(
    r'\+UUDF:([0-9A-Fa-f]{12}),(-?\d+),(-?\d+),(-?\d+),(\d+),(\d+),"([0-9A-Fa-f]{12})","",(\d+),(\d+)'
)

RADAR_CONFIG_COMMAND_DELAY_SECONDS = 0.12
RADAR_CONFIG_CONTROL_DELAY_SECONDS = 0.50
RADAR_CONFIG_RESPONSE_TIMEOUT_SECONDS = 2.0
RADAR_CONFIG_RESPONSE_POLL_SECONDS = 0.05
RADAR_CONFIG_DATA_PORT_COMMAND = f"configDataPort {RADAR_DATA_BAUD} 0"
DIAGNOSTIC_FLUSH_EVERY = 25
diagnostic_init_lock = threading.Lock()
diagnostic_run_dirs = {}


def get_diagnostic_run_dir():
    """Vrati adresar pro diagnosticky dump senzoru a vytvori ho pri prvnim pouziti."""
    if not CAPTURE_RAW_SERIAL:
        return None

    current_run_id = get_current_run_id()
    with diagnostic_init_lock:
        if current_run_id not in diagnostic_run_dirs:
            run_dir = DIAGNOSTIC_CAPTURE_DIR / current_run_id
            try:
                run_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                print(f"Diagnostic capture disabled: cannot create '{run_dir}': {exc}")
                diagnostic_run_dirs[current_run_id] = None
                return None
            metadata_path = run_dir / "metadata.json"
            metadata = {
                "run_id": current_run_id,
                "created_at_iso": datetime.now().isoformat(),
                "capture_raw_serial": True,
                "ble_ids": [cfg["id"] for cfg in BLE_CONFIGS],
                "radar_ids": [cfg["id"] for cfg in RADAR_CONFIGS],
            }
            try:
                metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError as exc:
                print(f"Diagnostic capture disabled: cannot write '{metadata_path}': {exc}")
                diagnostic_run_dirs[current_run_id] = None
                return None
            diagnostic_run_dirs[current_run_id] = run_dir
        return diagnostic_run_dirs[current_run_id]


class DiagnosticCapture:
    """Jednoduchy NDJSON logger pro nerozparserovana data jednoho senzoru."""

    def __init__(self, sensor_id, file_suffix):
        self.sensor_id = sensor_id
        self.file_suffix = file_suffix
        self.handle = None
        self.write_count = 0
        self.active_run_id = None
        self.disabled = False

    def write_record(self, record):
        if not CAPTURE_RAW_SERIAL or self.disabled:
            return

        current_run_id = get_current_run_id()
        if self.handle is None or self.active_run_id != current_run_id:
            self.close()
            run_dir = get_diagnostic_run_dir()
            if run_dir is None:
                self.disabled = True
                return
            path = run_dir / f"{self.sensor_id}_{self.file_suffix}.ndjson"
            try:
                self.handle = path.open("a", encoding="utf-8")
            except OSError as exc:
                print(f"Diagnostic capture disabled for {self.sensor_id}: cannot open '{path}': {exc}")
                self.disabled = True
                return
            self.active_run_id = current_run_id

        try:
            self.handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.write_count += 1
            if self.write_count % DIAGNOSTIC_FLUSH_EVERY == 0:
                self.handle.flush()
        except OSError as exc:
            print(f"Diagnostic capture disabled for {self.sensor_id}: write failed: {exc}")
            self.disabled = True
            self.close()

    def close(self):
        if self.handle:
            self.handle.flush()
            self.handle.close()
            self.handle = None
        self.active_run_id = None


def load_radar_config_commands(config_path):
    """Nacte radar cfg, odstrani komentare a doplni spravny configDataPort."""
    with open(config_path, "r", encoding="utf-8", errors="ignore") as file_handle:
        commands = []
        for line in file_handle:
            command = line.strip()
            if not command or command.startswith("%") or command.startswith("configDataPort "):
                continue
            commands.append(command)

    insert_index = None
    for index, command in enumerate(commands):
        if command.startswith("calibData "):
            insert_index = index
            break

    if insert_index is None:
        for index, command in enumerate(commands):
            if command == "sensorStart":
                insert_index = index
                break

    if insert_index is not None:
        commands.insert(insert_index, RADAR_CONFIG_DATA_PORT_COMMAND)
    else:
        commands.append(RADAR_CONFIG_DATA_PORT_COMMAND)

    return commands


def read_radar_command_response(ser):
    """Nacte odpoved CLI po jednom prikazu a pocka na finalni potvrzeni."""
    response = []
    deadline = time.monotonic() + RADAR_CONFIG_RESPONSE_TIMEOUT_SECONDS

    while time.monotonic() < deadline:
        if ser.in_waiting <= 0:
            time.sleep(RADAR_CONFIG_RESPONSE_POLL_SECONDS)
            continue

        raw_line = ser.readline()
        if not raw_line:
            continue

        line = raw_line.decode(errors="ignore").strip()
        if not line:
            continue

        response.append(line)
        if "Done" in line or "Error" in line or "mmwDemo:/>" in line:
            break

    return response


def sync_radar_cli(ser):
    """Vycte pripadne stare bajty a dostane CLI do promptu pred konfiguraci."""
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    ser.write(b"\n")
    ser.flush()
    time.sleep(RADAR_CONFIG_CONTROL_DELAY_SECONDS)
    read_radar_command_response(ser)


def send_radar_config_file(serial_handle, config_path):
    """Posle jeden konkretni radarovy profil do jiz otevreneho CLI portu."""
    commands = load_radar_config_commands(config_path)
    for cmd in commands:
        serial_handle.reset_input_buffer()
        serial_handle.write((cmd + "\n").encode())
        serial_handle.flush()
        delay = (
            RADAR_CONFIG_CONTROL_DELAY_SECONDS
            if cmd in {"sensorStop", "flushCfg", "sensorStart"}
            else RADAR_CONFIG_COMMAND_DELAY_SECONDS
        )
        time.sleep(delay)

        response = read_radar_command_response(serial_handle)
        has_done = any("Done" in line for line in response)
        has_prompt = any("mmwDemo:/>" in line for line in response)
        has_error = any("Error" in line or "not recognized as a CLI command" in line for line in response)
        if not has_done and (has_error or not has_prompt):
            raise RuntimeError(
                f"Prikaz '{cmd}' nebyl potvrzen. Odpoved radaru: {response}"
            )


def send_radar_config(cfg):
    """Posle do radaru konfiguracni profil."""
    try:
        print(f"Radar {cfg['id']}: Posilam konfiguraci na {cfg['cfg_port']}...")
        with serial.Serial(cfg["cfg_port"], RADAR_CFG_BAUD, timeout=1) as ser:
            sync_radar_cli(ser)
            try:
                send_radar_config_file(ser, RADAR_CONFIG_FILE)
            except Exception as primary_exc:
                bootstrap_path = str(RADAR_BOOTSTRAP_CONFIG_FILE)
                target_path = str(RADAR_CONFIG_FILE)
                if not bootstrap_path or bootstrap_path == target_path:
                    raise primary_exc

                print(
                    f"Radar {cfg['id']}: Primarni profil selhal, zkousim bootstrap "
                    f"'{RADAR_BOOTSTRAP_CONFIG_FILE.name}' a potom znovu '{RADAR_CONFIG_FILE.name}'."
                )
                sync_radar_cli(ser)
                send_radar_config_file(ser, RADAR_BOOTSTRAP_CONFIG_FILE)
                sync_radar_cli(ser)
                send_radar_config_file(ser, RADAR_CONFIG_FILE)
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
    diagnostic_capture = DiagnosticCapture(cfg["id"], "serial")

    while True:
        radar = None
        try:
            radar = RadarInterface(port=cfg["dat_port"], baudrate=RADAR_DATA_BAUD)
            print(f"Radar {cfg['id']}: Pripojen.")

            while True:
                raw_data = radar.read_data()
                if not raw_data:
                    continue

                parsed = radar.parse_frame(raw_data)
                diagnostic_capture.write_record(
                    {
                        "recorded_at": time.time(),
                        "sensor_id": cfg["id"],
                        "port": cfg["dat_port"],
                        "baudrate": RADAR_DATA_BAUD,
                        "bytes_len": len(raw_data),
                        "data_base64": base64.b64encode(raw_data).decode("ascii"),
                        "parsed_ok": bool(parsed),
                    }
                )
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
                    if INGEST_ENABLE_DB:
                        db_queue.put((cfg["id"], (get_current_run_id(), time.time(), x_g, y_g, z_g, snr, doppler)))

                if detections_for_print:
                    formatted = ", ".join(
                        f"(x={x:.2f}, y={y:.2f}, z={z:.2f}, dop={d:.2f}, snr={s})"
                        for x, y, z, s, d in detections_for_print
                    )
                    print(f"{cfg['id']} vidi: {formatted}")

        except Exception as exc:
            print(f"Radar {cfg['id']} Error: {exc}. Restart za 5s...")
            if radar is not None:
                try:
                    radar.close()
                except Exception:
                    pass
            time.sleep(5)
        finally:
            diagnostic_capture.close()


def ble_worker(cfg):
    """Cte jednu BLE kotvu, publikuje azimuty do MQTT a uklada je do DB."""
    mqtt_client = mqtt.Client(client_id=f"ingest_{cfg['id']}")
    mqtt_client.connect(MQTT_HOST, MQTT_PORT)
    mqtt_client.loop_start()
    diagnostic_capture = DiagnosticCapture(cfg["id"], "serial")

    while True:
        try:
            with serial.Serial(cfg["port"], cfg["baud"], timeout=1) as ser:
                print(f"BLE {cfg['id']}: Pripojen.")

                while True:
                    raw_line = ser.readline()
                    if not raw_line:
                        continue
                    timestamp = time.time()
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    match = AZIMUTH_PATTERN.match(line)
                    diagnostic_capture.write_record(
                        {
                            "recorded_at": timestamp,
                            "sensor_id": cfg["id"],
                            "port": cfg["port"],
                            "baudrate": cfg["baud"],
                            "decoded_text": line,
                            "data_base64": base64.b64encode(raw_line).decode("ascii"),
                            "matched_pattern": bool(match),
                        }
                    )
                    if not match:
                        continue

                    tag_id = match.group(1).upper()
                    rssi = int(match.group(2))
                    azimuth = int(match.group(3))
                    elevation = int(match.group(4))

                    payload = {
                        "timestamp": timestamp,
                        "tag_id": tag_id,
                        "rssi": rssi,
                        "azimuth": azimuth,
                        "elevation": elevation,
                    }
                    mqtt_client.publish(f"sensors/raw/{cfg['id']}", json.dumps(payload))
                    if INGEST_ENABLE_DB:
                        db_queue.put((cfg["id"], (get_current_run_id(), timestamp, tag_id, rssi, azimuth, elevation)))

        except Exception as exc:
            print(f"BLE {cfg['id']} Error: {exc}. Restart za 5s...")
            time.sleep(5)
        finally:
            diagnostic_capture.close()


if __name__ == "__main__":
    if INGEST_ENABLE_DB:
        threading.Thread(target=db_worker, daemon=True).start()
        print("DB worker enabled")
    else:
        print("DB worker disabled by FOUR_INGEST_ENABLE_DB=0")

    for cfg in RADAR_CONFIGS:
        if cfg["id"] not in ENABLED_SENSORS:
            print(f"Skipping radar worker: {cfg['id']}")
            continue
        threading.Thread(target=radar_worker, args=(cfg,), daemon=True).start()

    for cfg in BLE_CONFIGS:
        if cfg["id"] not in ENABLED_SENSORS:
            print(f"Skipping BLE worker: {cfg['id']}")
            continue
        threading.Thread(target=ble_worker, args=(cfg,), daemon=True).start()

    print("Sber dat spusten. Ukoncete pomoci Ctrl+C.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nUkoncuji system...")
