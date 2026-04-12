import asyncio
import json
import math
import sys
import time

import aiomqtt
import numpy as np
from sklearn.cluster import DBSCAN

from db_handler_1 import db_handler
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


def average_angles(angles_deg):
    """Vypočítá průměr úhlů s ohledem na kruhový přechod přes 360 stupňů."""
    if not angles_deg:
        return None
    sin_sum = sum(math.sin(math.radians(a)) for a in angles_deg)
    cos_sum = sum(math.cos(math.radians(a)) for a in angles_deg)
    return (math.degrees(math.atan2(sin_sum, cos_sum)) + 360) % 360


def find_matching_tag(center_x, center_y, ble_data_1, ble_data_2, active_tracks_keys):
    # Pomocná funkce pro průměrování úhlů
    def avg_angles(angles):
        if not angles: return None
        sin_sum = sum(math.sin(math.radians(a)) for a in angles)
        cos_sum = sum(math.cos(math.radians(a)) for a in angles)
        return (math.degrees(math.atan2(sin_sum, cos_sum)) + 360) % 360

    tag_azimuths = {}

    for row in ble_data_1:
        tag = row[2]
        if tag not in tag_azimuths: tag_azimuths[tag] = {'az1': [], 'az2': []}
        tag_azimuths[tag]['az1'].append(row[4])

    for row in ble_data_2:
        tag = row[2]
        if tag not in tag_azimuths: tag_azimuths[tag] = {'az1': [], 'az2': []}
        tag_azimuths[tag]['az2'].append(row[4])

    exp_1 = calculate_expected_angle(center_x, center_y, "ble_1")
    exp_2 = calculate_expected_angle(center_x, center_y, "ble_2")

    candidates = []

    for tag, az_data in tag_azimuths.items():
        if tag in active_tracks_keys:
            continue

        avg_az1 = avg_angles(az_data['az1'])
        avg_az2 = avg_angles(az_data['az2'])

        # --- NOVÉ: Triangulace a kontrola fyzické vzdálenosti ---
        if avg_az1 is not None and avg_az2 is not None:
            tag_pos = triangulate_ble(avg_az1, avg_az2)
            if tag_pos:
                dist = math.hypot(center_x - tag_pos[0], center_y - tag_pos[1])
                # Pokud je tag fyzicky dál než 0.3 metru od osoby, JEDNOZNAČNĚ TO ZAMÍTNOUT!
                if dist > 1.0:
                    continue

        diff1 = 0
        diff2 = 0
        count = 0

        if avg_az1 is not None:
            diff1 = abs((avg_az1 - exp_1 + 180) % 360 - 180)
            count += 1

        if avg_az2 is not None:
            diff2 = abs((avg_az2 - exp_2 + 180) % 360 - 180)
            count += 1

        if count == 0:
            continue

        avg_diff = (diff1 + diff2) / count

        # Pokud prošel vzdáleností, stačí mu volnější úhel 80 stupňů (kvůli šumu z rychlého pohybu)
        if avg_diff < 80.0:
            candidates.append({"tag": tag, "diff": avg_diff})

    if not candidates:
        return "unknown", 0.5, None

    # Vybereme tag, jehož těžiště ukazuje nejpřesněji
    candidates.sort(key=lambda x: x["diff"])
    return candidates[0]["tag"], 0.9, candidates

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

                    # KROK 2: Analýza radarových dat (Vytvoření seznamu shluků)
                    clusters = []
                    if len(all_radar_points) >= 3:
                        radar_points = np.array(all_radar_points, dtype=float)
                        clustering = DBSCAN(eps=0.5, min_samples=2).fit(radar_points)
                        labels = clustering.labels_
                        unique_labels = set(labels)
                        for k in unique_labels:
                            if k != -1:
                                class_member_mask = (labels == k)
                                xyz = radar_points[class_member_mask]
                                cx, cy, cz = np.mean(xyz, axis=0)
                                clusters.append((cx, cy, cz))

                    matched_clusters = set()
                    matched_tids = set()

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

                        if best_idx != -1:
                            matched_clusters.add(best_idx)
                            matched_tids.add(tid)
                            track.update(clusters[best_idx][0], clusters[best_idx][1])
                            track.current_z = clusters[best_idx][2]
                            track.age = 0.0
                        else:
                            # --- NOVÉ: TŘENÍ ---
                            # Pokud stopa zrovna nemá svůj radar (např. v chumlu 5 lidí),
                            # rychle zabrzdí, aby neuletěla jako duch ze scény.
                            track.state[2] *= 0.5  # Zpomalení osy X
                            track.state[3] *= 0.5  # Zpomalení osy Y

                    # KROK 3: Přiřazení shluků k existujícím stopám (Podle VZDÁLENOSTI)
                    matched_clusters = set()
                    renames = {}

                    for tid, track in active_tracks.items():
                        best_idx = -1
                        min_dist = 1.5

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

                                    # --- OPRAVENÉ: Detekce zahozeného tagu pomocí VZDÁLENOSTI ---
                                else:
                                        my_b1_angles = [r[4] for r in b1 if r[2] == tid]
                                        my_b2_angles = [r[4] for r in b2 if r[2] == tid]

                                        def avg_angles(angles):
                                            if not angles: return None
                                            sin_sum = sum(math.sin(math.radians(a)) for a in angles)
                                            cos_sum = sum(math.cos(math.radians(a)) for a in angles)
                                            return (math.degrees(math.atan2(sin_sum, cos_sum)) + 360) % 360

                                        avg_1 = avg_angles(my_b1_angles)
                                        avg_2 = avg_angles(my_b2_angles)

                                        dropped = False

                                        # Hlavní metoda: Triangulace (výpočet fyzické vzdálenosti v metrech)
                                        if avg_1 is not None and avg_2 is not None:
                                            tag_pos = triangulate_ble(avg_1, avg_2)
                                            if tag_pos:
                                                tx, ty = tag_pos
                                                # Vzdálenost mezi radarovou tečkou a fyzickým místem tagu
                                                dist = math.hypot(rx - tx, ry - ty)
                                                # Zahozeno, pokud je tag fyzicky dál než 1.0 metru od osoby
                                                if dist > 1.0:
                                                    dropped = True
                                        else:
                                            # Záložní metoda: Pokud tag vidí jen jeden senzor (slepý úhel), kontrolujeme úhel
                                            exp_1 = calculate_expected_angle(rx, ry, "ble_1")
                                            exp_2 = calculate_expected_angle(rx, ry, "ble_2")
                                            diff_1 = abs((avg_1 - exp_1 + 180) % 360 - 180) if avg_1 is not None else 0
                                            diff_2 = abs((avg_2 - exp_2 + 180) % 360 - 180) if avg_2 is not None else 0

                                            if (avg_1 is not None and diff_1 > 45.0) or (
                                                    avg_2 is not None and diff_2 > 45.0):
                                                dropped = True

                                        if dropped:
                                            renames[tid] = f"unknown_{int(time.time() * 1000)}_drop"

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

                    # KROK 5: Příprava dat pro Web a DB
                    for tid, track in active_tracks.items():
                        smooth_x = float(track.state[0])
                        smooth_y = float(track.state[1])
                        smooth_z = getattr(track, "current_z", 0.92)

                        conf = 0.9 if track.age == 0.0 else 0.5
                        opacity = max(0.0, 1.0 - (track.age / 4.0))

                        final_fused_batch.append((time.time(), tid, smooth_x, smooth_y, smooth_z, conf))
                        fused_output_for_web.append({
                            "tag_id": tid,
                            "x": smooth_x,
                            "y": smooth_y,
                            "z": smooth_z,
                            "confidence": conf,
                            "opacity": opacity
                        })

                    # KROK 6: Smazání "mrtvých" stop
                    # Zvýšili jsme přežití stopy na 4.0 vteřiny, aby stihla na monitoru plynule vyblednout a zmizet
                    stale_ids = [tid for tid, track in active_tracks.items() if track.age > 4.0]
                    for tid in stale_ids:
                        del active_tracks[tid]

                    # --- OPRAVA ZAMRZÁNÍ ---
                    # Odebrali jsme slovíčko 'if' - backend teď posílá data neustále, i když je místnost prázdná
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
