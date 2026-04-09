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


def find_matching_tag(center_x, center_y, ble_data_1, ble_data_2, active_tracks_keys):
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

    # Odstranit z kandidátů ty, kteří už jsou aktivně sledováni
    valid_candidates = [c for c in found_candidates if c["tag"] not in active_tracks_keys]

    if not valid_candidates:
        return "unknown", 0.5, None

    valid_candidates.sort(key=lambda x: x["rssi"], reverse=True)
    return valid_candidates[0]["tag"], 0.9, valid_candidates


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

                    current_time = time.time()

                    async with buffer_lock:
                        r1 = [(d["x"], d["y"], d["z"]) for d in sensor_buffers["radar_1"]]
                        r2 = [(d["x"], d["y"], d["z"]) for d in sensor_buffers["radar_2"]]

                        # Udržíme BLE data z poslední 1 sekundy, abychom překlenuli výpadky
                        valid_b1 = [d for d in sensor_buffers["ble_1"] if current_time - d["timestamp"] <= 1.0]
                        valid_b2 = [d for d in sensor_buffers["ble_2"] if current_time - d["timestamp"] <= 1.0]

                        b1 = [(0, d["timestamp"], d.get("tag_id", "unknown"), d["rssi"], d["azimuth"]) for d in
                              valid_b1]
                        b2 = [(0, d["timestamp"], d.get("tag_id", "unknown"), d["rssi"], d["azimuth"]) for d in
                              valid_b2]

                        sensor_buffers["radar_1"].clear()
                        sensor_buffers["radar_2"].clear()
                        sensor_buffers["ble_1"] = valid_b1
                        sensor_buffers["ble_2"] = valid_b2

                    all_radar_points = r1 + r2
                    final_fused_batch = []
                    fused_output_for_web = []

                    # KROK 1: Všechny aktivní stopy posuneme dopředu (predikce filtru)
                    track_ids = list(active_tracks.keys())
                    coasting_tracks = set()

                    for track in active_tracks.values():
                        track.predict()
                        track.age += 0.15  # Správné dt pro stárnutí stop

                    # Detekce křížení (vzdálenost < 0.4 m)
                    for i in range(len(track_ids)):
                        for j in range(i + 1, len(track_ids)):
                            t1 = active_tracks[track_ids[i]]
                            t2 = active_tracks[track_ids[j]]
                            dist = math.hypot(t1.state[0] - t2.state[0], t1.state[1] - t2.state[1])

                            if dist < 0.4:
                                coasting_tracks.add(track_ids[i])
                                coasting_tracks.add(track_ids[j])

                    # KROK 2: Analýza radarových dat (Vytvoření seznamu shluků)
                    clusters = []
                    if len(all_radar_points) >= 3:
                        coords_xy = np.array([[p[0], p[1]] for p in all_radar_points])
                        coords_z = np.array([p[2] for p in all_radar_points])

                        db = DBSCAN(eps=0.4, min_samples=3).fit(coords_xy)

                        for cluster_id in set(db.labels_):
                            if cluster_id == -1:
                                continue

                            mask = db.labels_ == cluster_id
                            raw_x, raw_y = np.mean(coords_xy[mask], axis=0)
                            raw_z = np.mean(coords_z[mask])
                            clusters.append((raw_x, raw_y, raw_z))

                    # KROK 3: Přiřazení shluků k existujícím stopám (Podle VZDÁLENOSTI)
                    matched_clusters = set()
                    renames = {}

                    for tid, track in active_tracks.items():
                        best_idx = -1
                        min_dist = 0.8

                        for i, (rx, ry, rz) in enumerate(clusters):
                            if i in matched_clusters:
                                continue

                            dist = math.hypot(track.state[0] - rx, track.state[1] - ry)
                            if dist < min_dist:
                                min_dist = dist
                                best_idx = i

                        # Pokud jsme našli nejbližší bod
                        if best_idx != -1:
                            matched_clusters.add(best_idx)
                            rx, ry, rz = clusters[best_idx]

                            if tid not in coasting_tracks:
                                track.update(rx, ry)
                                track.current_z = float(rz)

                            # Pokus o upgrade identity z 'unknown' na reálný BLE tag
                            if str(tid).startswith("unknown"):
                                new_tag_id, conf, _ = find_matching_tag(rx, ry, b1, b2, active_tracks.keys())
                                if new_tag_id != "unknown" and new_tag_id not in renames.values():
                                    renames[tid] = new_tag_id

                    # Aplikace přejmenování (upgrade jména za běhu)
                    for old_tid, new_tid in renames.items():
                        active_tracks[new_tid] = active_tracks.pop(old_tid)
                        if old_tid in coasting_tracks:
                            coasting_tracks.remove(old_tid)
                            coasting_tracks.add(new_tid)

                    # KROK 4: Zpracování zbylých nepřiřazených shluků (NOVÉ osoby)
                    for i, (rx, ry, rz) in enumerate(clusters):
                        if i not in matched_clusters:
                            tag_id, confidence, _ = find_matching_tag(rx, ry, b1, b2, active_tracks.keys())

                            if tag_id == "unknown" or tag_id in active_tracks:
                                tag_id = f"unknown_{int(time.time() * 1000)}_{i}"
                                confidence = 0.5

                            active_tracks[tag_id] = KalmanObject(rx, ry, dt=0.15)
                            active_tracks[tag_id].update(rx, ry)
                            active_tracks[tag_id].current_z = float(rz)

                    # KROK 5: Příprava dat pro Web a DB (Nezávisle na tom, zda radar viděl nebo ne)
                    for tid, track in active_tracks.items():
                        smooth_x = float(track.state[0])
                        smooth_y = float(track.state[1])

                        smooth_z = getattr(track, "current_z", 0.92)

                        # Pokud objekt letí naslepo (coasting), snížíme mu confidence
                        conf = 0.5 if tid in coasting_tracks else 0.9

                        final_fused_batch.append((time.time(), tid, smooth_x, smooth_y, smooth_z, conf))
                        fused_output_for_web.append({
                            "tag_id": tid,
                            "x": smooth_x,
                            "y": smooth_y,
                            "z": smooth_z,
                            "confidence": conf,
                        })

                    # KROK 6: Smazání "mrtvých" stop
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