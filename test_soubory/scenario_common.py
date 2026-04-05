import asyncio
import json
import math
import random
import time

import paho.mqtt.client as mqtt

from Four.db_handler import db_handler


MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
PUBLISH_PERIOD_SECONDS = 0.5

RADAR_CONFIGS = [
    {"id": "radar_1", "pos_x": 1.5, "pos_y": 0.0, "pos_z": 0.7, "rotation": 90},
    {"id": "radar_2", "pos_x": 0.0, "pos_y": 1.5, "pos_z": 0.7, "rotation": 0},
]

BLE_CONFIGS = [
    {"id": "ble_1", "pos_x": 2.5, "pos_y": 0.0, "pos_z": 0.7, "rotation": 90},
    {"id": "ble_2", "pos_x": 0.0, "pos_y": 3.0, "pos_z": 0.7, "rotation": 0},
]


class ObjectState:
    def __init__(self, tag_id, x, y, z=0.92, vx=0.0, vy=0.0):
        self.tag_id = tag_id
        self.x = x
        self.y = y
        self.z = z
        self.vx = vx
        self.vy = vy


def transform_to_global(x_loc, y_loc, z_loc, cfg):
    angle_rad = math.radians(cfg["rotation"])
    x_glob = x_loc * math.cos(angle_rad) - y_loc * math.sin(angle_rad)
    y_glob = x_loc * math.sin(angle_rad) + y_loc * math.cos(angle_rad)
    return x_glob + cfg["pos_x"], y_glob + cfg["pos_y"], z_loc + cfg["pos_z"]


def transform_to_local(x_glob, y_glob, z_glob, cfg):
    dx = x_glob - cfg["pos_x"]
    dy = y_glob - cfg["pos_y"]
    dz = z_glob - cfg["pos_z"]
    angle_rad = math.radians(cfg["rotation"])
    x_loc = dx * math.cos(angle_rad) + dy * math.sin(angle_rad)
    y_loc = -dx * math.sin(angle_rad) + dy * math.cos(angle_rad)
    return x_loc, y_loc, dz


def normalize_angle(angle_deg):
    return ((angle_deg + 180.0) % 360.0) - 180.0


def build_radar_records(objects, cfg, timestamp):
    records = []

    for obj in objects:
        x_loc, y_loc, z_loc = transform_to_local(obj.x, obj.y, obj.z, cfg)
        distance = math.sqrt(x_loc ** 2 + y_loc ** 2 + z_loc ** 2)
        azimuth_local = math.degrees(math.atan2(y_loc, x_loc))

        if x_loc <= 0.0 or distance > 5.0 or abs(azimuth_local) > 70.0:
            continue

        cluster_size = random.randint(3, 5)
        for _ in range(cluster_size):
            point_x_loc = x_loc + random.uniform(-0.12, 0.12)
            point_y_loc = y_loc + random.uniform(-0.12, 0.12)
            point_z_loc = z_loc + random.uniform(-0.04, 0.04)
            point_x_glob, point_y_glob, point_z_glob = transform_to_global(point_x_loc, point_y_loc, point_z_loc, cfg)
            snr = max(7.0, 23.0 - distance * 2.6 + random.uniform(-1.8, 1.8))
            records.append(
                (
                    timestamp,
                    round(point_x_glob, 3),
                    round(point_y_glob, 3),
                    round(point_z_glob, 3),
                    round(snr, 2),
                )
            )

    return records


def build_ble_records(objects, cfg, timestamp):
    records = []

    for obj in objects:
        dx = obj.x - cfg["pos_x"]
        dy = obj.y - cfg["pos_y"]
        dz = obj.z - cfg["pos_z"]
        distance = math.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
        world_angle = math.degrees(math.atan2(dy, dx))
        relative_azimuth = normalize_angle(world_angle - cfg["rotation"])

        if distance > 8.0 or abs(relative_azimuth) > 85.0:
            continue

        cluster_size = random.randint(3, 5)
        expected_rssi = -45.0 - distance * 9.0
        for _ in range(cluster_size):
            azimuth = relative_azimuth + random.uniform(-3.5, 3.5)
            rssi = int(round(expected_rssi + random.uniform(-2.0, 2.0)))
            records.append((timestamp, obj.tag_id, rssi, round(azimuth, 2)))

    return records


async def publish_and_store(mqtt_client, sensor_name, records, is_radar):
    for record in records:
        if is_radar:
            payload = {
                "timestamp": record[0],
                "x": record[1],
                "y": record[2],
                "z": record[3],
                "snr": record[4],
            }
        else:
            payload = {
                "timestamp": record[0],
                "tag_id": record[1],
                "rssi": record[2],
                "azimuth": record[3],
            }

        mqtt_client.publish(f"sensors/raw/{sensor_name}", json.dumps(payload))

    if records:
        await db_handler.insert_batch(sensor_name, records)


async def run_scenario(scenario_name, objects, update_fn):
    mqtt_client = mqtt.Client(client_id=f"scenario_{scenario_name}")
    mqtt_client.connect(MQTT_HOST, MQTT_PORT)
    mqtt_client.loop_start()

    await db_handler.connect()
    await db_handler.init_tables()

    print(f"Running scenario: {scenario_name}. Stop with Ctrl+C.")
    step_index = 0

    try:
        while True:
            cycle_started = time.time()
            update_fn(step_index, objects, PUBLISH_PERIOD_SECONDS)

            for cfg in RADAR_CONFIGS:
                records = build_radar_records(objects, cfg, cycle_started)
                await publish_and_store(mqtt_client, cfg["id"], records, is_radar=True)

            for cfg in BLE_CONFIGS:
                records = build_ble_records(objects, cfg, cycle_started)
                await publish_and_store(mqtt_client, cfg["id"], records, is_radar=False)

            step_index += 1
            elapsed = time.time() - cycle_started
            await asyncio.sleep(max(0.0, PUBLISH_PERIOD_SECONDS - elapsed))
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
