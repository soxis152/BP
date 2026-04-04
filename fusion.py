import time
import math
import asyncio
import numpy as np
from sklearn.cluster import DBSCAN
from kalman_filter import KalmanObject

# NOVÝ IMPORT - načítáme naši asynchronní třídu
from db_handler import db_handler

# --- KONFIGURACE (Sjednoceno s ingestion.py) ---
SENSORS = {
    "ble_1": {"x": 2.5, "y": 0.0, "z": 0.7, "rotation": 90},
    "ble_2": {"x": 0.0, "y": 3.0, "z": 0.7, "rotation": 0}
}

active_tracks = {}


# --- NOVÁ FUNKCE: TRIANGULACE ---
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
    except:
        return None


# --- STÁVAJÍCÍ POMOCNÉ FUNKCE ---
def calculate_expected_angle(obj_x, obj_y, sensor_id):
    cfg = SENSORS[sensor_id]
    dx = obj_x - cfg["x"]
    dy = obj_y - cfg["y"]
    angle_deg = math.degrees(math.atan2(dy, dx))
    return (angle_deg - cfg["rotation"] + 360) % 360


def find_matching_tag(center_x, center_y, ble_data_1, ble_data_2):
    threshold = 15.0
    found_candidates = []

    exp_1 = calculate_expected_angle(center_x, center_y, "ble_1")
    for row in ble_data_1:
        # row: (id, timestamp, tag_id, rssi, azimuth)
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


# --- HLAVNÍ PROCES FÚZE (Nyní asynchronní!) ---
async def perform_fusion():
    print("--- FUSION ENGINE + KALMAN 3D + TRIANGULATION (ASYNC) ---")

    # 1. Připojení k DB poolu
    await db_handler.connect()

    while True:
        try:
            window_limit = time.time() - 0.4

            # Kontrola, zda je spojení aktivní
            if db_handler.pool is None:
                await asyncio.sleep(0.1)
                continue

            # 2. Asynchronní vyčtení dat z databáze (neblokuje zbytek systému)
            async with db_handler.pool.acquire() as conn:
                r1_records = await conn.fetch("SELECT x, y, z FROM radar_1 WHERE timestamp > $1", window_limit)
                r2_records = await conn.fetch("SELECT x, y, z FROM radar_2 WHERE timestamp > $1", window_limit)

                b1_records = await conn.fetch(
                    "SELECT id, timestamp, tag_id, rssi, azimuth FROM ble_1 WHERE timestamp > $1", window_limit)
                b2_records = await conn.fetch(
                    "SELECT id, timestamp, tag_id, rssi, azimuth FROM ble_2 WHERE timestamp > $1", window_limit)

            # Knihovna asyncpg vrací typ "Record". Převedeme je na klasická pole (tuples),
            # aby váš starý algoritmus (DBSCAN atd.) neměl problém:
            r1 = [(r['x'], r['y'], r['z']) for r in r1_records]
            r2 = [(r['x'], r['y'], r['z']) for r in r2_records]
            b1 = [(b['id'], b['timestamp'], b['tag_id'], b['rssi'], b['azimuth']) for b in b1_records]
            b2 = [(b['id'], b['timestamp'], b['tag_id'], b['rssi'], b['azimuth']) for b in b2_records]

            all_radar_points = r1 + r2
            final_fused_batch = []

            # --- SCÉNÁŘ A: RADAR VIDÍ OBJEKTY (Priorita) ---
            if len(all_radar_points) >= 3:
                coords_xy = np.array([[p[0], p[1]] for p in all_radar_points])
                coords_z = np.array([p[2] for p in all_radar_points])
                db = DBSCAN(eps=0.4, min_samples=3).fit(coords_xy)

                for cluster_id in set(db.labels_):
                    if cluster_id == -1: continue

                    mask = (db.labels_ == cluster_id)
                    raw_x, raw_y = np.mean(coords_xy[mask], axis=0)
                    raw_z = np.mean(coords_z[mask])

                    # Identifikace a získání azimutů
                    tag_id, confidence, candidates = find_matching_tag(raw_x, raw_y, b1, b2)

                    # Kalmanova filtrace
                    if tag_id not in active_tracks:
                        active_tracks[tag_id] = KalmanObject(raw_x, raw_y, dt=0.15)

                    active_tracks[tag_id].predict()
                    active_tracks[tag_id].update(raw_x, raw_y)

                    smooth_x = float(active_tracks[tag_id].state[0])
                    smooth_y = float(active_tracks[tag_id].state[1])

                    final_fused_batch.append((time.time(), tag_id, smooth_x, smooth_y, float(raw_z), confidence))

            # --- SCÉNÁŘ B: RADAR JE SLEPÝ, ALE BLE TRIANGULUJE ---
            # Zde později dopíšete logiku

            # 3. Asynchronní zápis fúzovaných dat zpět do DB
            if final_fused_batch:
                await db_handler.insert_batch("fused_data", final_fused_batch)

        except Exception as e:
            print(f"Fusion Error: {e}")

        # Místo time.sleep použijeme asynchronní asyncio.sleep
        await asyncio.sleep(0.15)


if __name__ == "__main__":
    # Spouštíme asynchronní aplikaci správným způsobem
    asyncio.run(perform_fusion())