import asyncio
import json
import math
import sys
import time

import aiomqtt
import numpy as np
from sklearn.cluster import DBSCAN

from db_handler import db_handler
from kalman_filter import KalmanObject

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Unified with ingestion.py
SENSORS = {
    "ble_1": {"x": 1.5, "y": 0.0, "z": 0.7, "rotation": 90},
    "ble_2": {"x": 0.0, "y": 1.5, "z": 0.7, "rotation": 0},
}

active_tracks = {}
sensor_buffers = {
    "radar_1": [],
    "radar_2": [],
    "ble_1": [],
    "ble_2": [],
}
buffer_lock = asyncio.Lock()


def triangulate_ble(angle1_deg, angle2_deg):
    rad1 = math.radians(angle1_deg + SENSORS["ble_1"]["rotation"])
    rad2 = math.radians(angle2_deg + SENSORS["ble_2"]["rotation"])

    x1, y1 = SENSORS["ble_1"]["x"], SENSORS["ble_1"]["y"]
    x2, y2 = SENSORS["ble_2"]["x"], SENSORS["ble_2"]["y"]

    try:
        denom = math.cos(rad1) * (-math.sin(rad2)) - math.sin(rad1) * (-math.cos(rad2))
        if abs(denom) < 0.001:
            return None

        t = ((x2 - x1) * (-math.sin(rad2)) - (y2 - y1) * (-math.cos(rad2))) / denom
        tx = x1 + t * math.cos(rad1)
        ty = y1 + t * math.sin(rad1)
        return float(tx), float(ty)
    except Exception:
        return None


def calculate_expected_angle(obj_x, obj_y, sensor_id):
    cfg = SENSORS[sensor_id]
    dx = obj_x - cfg["x"]
    dy = obj_y - cfg["y"]
    angle_deg = math.degrees(math.atan2(dy, dx))
    return (angle_deg - cfg["rotation"] + 360) % 360


def find_matching_tag(center_x, center_y, ble_data_1, ble_data_2):
    threshold = 35.0
    found_candidates = []

    exp_1 = calculate_expected_angle(center_x, center_y, "ble_1")
    for row in ble_data_1:
        diff = abs((row[4] - exp_1 + 180) % 360 - 180)
        if diff < threshold:
            found_candidates.append({"tag": row[2], "rssi": row[3], "azimuth": row[4]})

    exp_2 = calculate_expected_angle(center_x, center_y, "ble_2")
    for row in ble_data_2:
        diff = abs((row[4] - exp_2 + 180) % 360 - 180)
        if diff < threshold:
            found_candidates.append({"tag": row[2], "rssi": row[3], "azimuth": row[4]})

    if not found_candidates:
        return "unknown", 0.5, None

    found_candidates.sort(key=lambda x: x["rssi"], reverse=True)
    return found_candidates[0]["tag"], 0.9, found_candidates


async def listen_raw_sensors():
    while True:
        try:
            async with aiomqtt.Client("127.0.0.1") as client:
                await client.subscribe("sensors/raw/#")
                print("Fusion: Listening to raw sensors on MQTT topic sensors/raw/#")

                async for message in client.messages:
                    topic = str(message.topic)
                    data = json.loads(message.payload.decode())

                    async with buffer_lock:
                        if "radar_1" in topic:
                            sensor_buffers["radar_1"].append(data)
                        elif "radar_2" in topic:
                            sensor_buffers["radar_2"].append(data)
                        elif "ble_1" in topic:
                            sensor_buffers["ble_1"].append(data)
                        elif "ble_2" in topic:
                            sensor_buffers["ble_2"].append(data)
        except aiomqtt.MqttError:
            print("Fusion listener: MQTT connection lost, retrying in 2s...")
            await asyncio.sleep(2)


async def perform_fusion_loop():
    await db_handler.connect()

    while True:
        try:
            async with aiomqtt.Client("127.0.0.1") as mqtt_client:
                while True:
                    await asyncio.sleep(0.15)

                    async with buffer_lock:
                        r1 = [(d["x"], d["y"], d["z"]) for d in sensor_buffers["radar_1"]]
                        r2 = [(d["x"], d["y"], d["z"]) for d in sensor_buffers["radar_2"]]
                        b1 = [(0, d["timestamp"], d.get("tag_id", "unknown"), d["rssi"], d["azimuth"]) for d in
                              sensor_buffers["ble_1"]]
                        b2 = [(0, d["timestamp"], d.get("tag_id", "unknown"), d["rssi"], d["azimuth"]) for d in
                              sensor_buffers["ble_2"]]

                        for key in sensor_buffers:
                            sensor_buffers[key].clear()

                    all_radar_points = r1 + r2
                    final_fused_batch = []
                    fused_output_for_web = []

                    # KROK 1: Všechny aktivní stopy posuneme dopředu (predikce filtru)
                    for track in active_tracks.values():
                        track.predict()

                    # KROK 2: Analýza radarových dat
                    if len(all_radar_points) >= 3:
                        coords_xy = np.array([[p[0], p[1]] for p in all_radar_points])
                        coords_z = np.array([p[2] for p in all_radar_points])

                        # ZVÝŠENO eps=0.8 (z 0.4), aby člověk netvořil víc shluků
                        db = DBSCAN(eps=0.4, min_samples=3).fit(coords_xy)

                        for cluster_id in set(db.labels_):
                            if cluster_id == -1:
                                continue

                            mask = db.labels_ == cluster_id
                            raw_x, raw_y = np.mean(coords_xy[mask], axis=0)
                            raw_z = np.mean(coords_z[mask])

                            # Pokus o párování s BLE
                            tag_id, confidence, _ = find_matching_tag(raw_x, raw_y, b1, b2)

                            # NOVÁ LOGIKA: Pokud BLE selhalo, zkusíme najít nejbližší už sledovaný objekt
                            if tag_id == "unknown":
                                closest_id = None
                                min_dist = 1.0  # Hledáme v okruhu max 1 metr
                                for tid, track in active_tracks.items():
                                    dist = math.hypot(track.state[0] - raw_x, track.state[1] - raw_y)
                                    if dist < min_dist:
                                        min_dist = dist
                                        closest_id = tid

                                if closest_id:
                                    tag_id = closest_id  # BLE sice nevíme, ale je to pořád ta samá osoba
                                else:
                                    # Je to úplně nový člověk bez tagu
                                    tag_id = f"unknown_{int(time.time() * 1000)}"

                            # Přidání nového cíle, pokud ještě neexistuje
                            if tag_id not in active_tracks:
                                active_tracks[tag_id] = KalmanObject(raw_x, raw_y, dt=0.15)

                            # KROK 3: Aktualizace filtru skutečnou naměřenou hodnotou
                            active_tracks[tag_id].update(raw_x, raw_y)

                            smooth_x = float(active_tracks[tag_id].state[0])
                            smooth_y = float(active_tracks[tag_id].state[1])

                            final_fused_batch.append(
                                (time.time(), tag_id, smooth_x, smooth_y, float(raw_z), confidence))
                            fused_output_for_web.append({
                                "tag_id": tag_id,
                                "x": smooth_x,
                                "y": smooth_y,
                                "z": float(raw_z),
                                "confidence": confidence,
                            })

                    # KROK 4: Smazání "mrtvých" stop (objekt odešel)
                    stale_ids = [tid for tid, track in active_tracks.items() if track.age > 2.0]
                    for tid in stale_ids:
                        del active_tracks[tid]

                    if fused_output_for_web:
                        payload = json.dumps({"type": "update", "objects": fused_output_for_web})
                        await mqtt_client.publish("sensors/fused", payload)

                    if final_fused_batch and db_handler.pool:
                        await db_handler.insert_batch("fused_data", final_fused_batch)
        except aiomqtt.MqttError:
            print("Fusion loop: MQTT connection lost, retrying in 2s...")
            await asyncio.sleep(2)
        except Exception as exc:
            print(f"Fusion loop error: {exc}")
            await asyncio.sleep(0.5)


async def main_fusion():
    print("--- FUSION ENGINE + KALMAN 3D + TRIANGULATION (MQTT ENABLED) ---")
    await asyncio.gather(listen_raw_sensors(), perform_fusion_loop())


if __name__ == "__main__":
    asyncio.run(main_fusion())
