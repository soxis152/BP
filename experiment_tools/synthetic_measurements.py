"""Helpery pro generovani syntetickych radar/BLE mereni z ground truth objektu."""

from __future__ import annotations

import json
import math
import random

try:
    from Four.config import RUN_ID
    from Four.db_handler import db_handler
except ImportError:
    try:
        from config import RUN_ID
        from db_handler import db_handler
    except ImportError:
        from ..config import RUN_ID
        from ..db_handler import db_handler


MAX_SYNTHETIC_SPEED_MPS = 4.0


class ObjectState:
    """Jednoduchy stav jednoho sledovaneho objektu."""

    def __init__(self, tag_id, x, y, z=0.92, vx=0.0, vy=0.0):
        self.tag_id = tag_id
        self.x = x
        self.y = y
        self.z = z
        self.vx = vx
        self.vy = vy
        self.radar_visible = True
        self.ble_visible = True
        self.radar_noise_xy = 0.0
        self.radar_noise_z = 0.0
        self.ble_azimuth_noise = 0.0
        self.ble_elevation_noise = 0.0
        self.ble_rssi_noise = 0.0


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


def update_object_velocities(objects, previous_positions, dt):
    if dt <= 0.0:
        return

    for obj in objects:
        previous = previous_positions.get(id(obj))
        if previous is None:
            continue

        prev_x, prev_y = previous
        vx = (obj.x - prev_x) / dt
        vy = (obj.y - prev_y) / dt
        speed = math.hypot(vx, vy)

        if speed > MAX_SYNTHETIC_SPEED_MPS:
            obj.vx = 0.0
            obj.vy = 0.0
            continue

        obj.vx = vx
        obj.vy = vy


def estimate_radial_doppler(obj, cfg):
    dx = obj.x - cfg["pos_x"]
    dy = obj.y - cfg["pos_y"]
    distance_xy = math.hypot(dx, dy)
    if distance_xy <= 0.001:
        return 0.0
    return (obj.vx * dx + obj.vy * dy) / distance_xy


def build_radar_records(objects, cfg, timestamp):
    records = []

    for obj in objects:
        if not obj.radar_visible:
            continue

        x_loc, y_loc, z_loc = transform_to_local(obj.x, obj.y, obj.z, cfg)
        distance = math.sqrt(x_loc**2 + y_loc**2 + z_loc**2)
        azimuth_local = math.degrees(math.atan2(y_loc, x_loc))

        if x_loc <= 0.0 or distance > 5.0 or abs(azimuth_local) > 70.0:
            continue

        cluster_size = random.randint(3, 5)
        for _ in range(cluster_size):
            point_x_loc = x_loc + random.uniform(-0.12, 0.12) + random.gauss(0.0, obj.radar_noise_xy)
            point_y_loc = y_loc + random.uniform(-0.12, 0.12) + random.gauss(0.0, obj.radar_noise_xy)
            point_z_loc = z_loc + random.uniform(-0.04, 0.04) + random.gauss(0.0, obj.radar_noise_z)
            point_x_glob, point_y_glob, point_z_glob = transform_to_global(point_x_loc, point_y_loc, point_z_loc, cfg)
            snr = max(7.0, 23.0 - distance * 2.6 + random.uniform(-1.8, 1.8))
            doppler = estimate_radial_doppler(obj, cfg)

            records.append(
                (
                    timestamp,
                    round(point_x_glob, 3),
                    round(point_y_glob, 3),
                    round(point_z_glob, 3),
                    round(snr, 2),
                    round(doppler, 3),
                )
            )

    return records


def build_ble_records(objects, cfg, timestamp):
    records = []

    for obj in objects:
        if not obj.ble_visible:
            continue

        dx = obj.x - cfg["pos_x"]
        dy = obj.y - cfg["pos_y"]
        dz = obj.z - cfg["pos_z"]
        distance = math.sqrt(dx**2 + dy**2 + dz**2)
        world_angle = math.degrees(math.atan2(dy, dx))
        relative_azimuth = normalize_angle(world_angle - cfg["rotation"])
        horizontal_distance = math.hypot(dx, dy)
        relative_elevation = math.degrees(math.atan2(dz, horizontal_distance))

        if distance > 8.0 or abs(relative_azimuth) > 85.0 or abs(relative_elevation) > 65.0:
            continue

        cluster_size = random.randint(3, 5)
        expected_rssi = -45.0 - distance * 9.0
        for _ in range(cluster_size):
            azimuth = relative_azimuth + random.uniform(-3.5, 3.5) + random.gauss(0.0, obj.ble_azimuth_noise)
            elevation = relative_elevation + random.uniform(-2.0, 2.0) + random.gauss(0.0, obj.ble_elevation_noise)
            rssi = int(round(expected_rssi + random.uniform(-2.0, 2.0) + random.gauss(0.0, obj.ble_rssi_noise)))
            records.append((timestamp, obj.tag_id, rssi, round(azimuth, 2), round(elevation, 2)))

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
                "doppler": record[5],
            }
        else:
            payload = {
                "timestamp": record[0],
                "tag_id": record[1],
                "rssi": record[2],
                "azimuth": record[3],
                "elevation": record[4],
            }

        mqtt_client.publish(f"sensors/raw/{sensor_name}", json.dumps(payload))

    if records:
        db_records = [(RUN_ID, *record) for record in records]
        await db_handler.insert_batch(sensor_name, db_records)
