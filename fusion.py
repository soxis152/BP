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

# Tento modul je matematické jádro celého systému.
#
# Úloha fusion vrstvy:
# 1. převzít syrové radarové body a BLE měření z MQTT,
# 2. z radarových bodů vytvořit shluky odpovídající fyzickým objektům,
# 3. udržovat pro každý objekt stopu pomocí Kalmanova filtru,
# 4. přiřadit radarové stopě identitu BLE tagu, pokud to dává geometricky smysl,
# 5. poslat výslednou scénu dál do frontendu a uložit ji do databáze.
#
# Filosofie systému:
# - Radar je "pán" polohy. Pozice objektu vzniká primárně z radarových dat.
# - BLE je "pán" identity. Pomáhá určit, který radarový objekt patří kterému tagu.
# - Kalmanův filtr vyhlazuje trajektorii a krátkodobě drží stopu při výpadku měření.
# - Pokud BLE přestane odpovídat radarové poloze, identita se může vrátit zpět na unknown.

# Geometrie BLE kotev musí odpovídat ingestion vrstvě. Pokud by zde byly jiné souřadnice
# než při sběru dat, neodpovídala by triangulace ani výpočet očekávaných úhlů realitě.
SENSORS = {
    "ble_1": {"x": 1.5, "y": 0.0, "z": 0.7, "rotation": 90},
    "ble_2": {"x": 0.0, "y": 1.5, "z": 0.7, "rotation": 0},
}

# active_tracks obsahuje všechny právě živé stopy.
# Klíčem je buď skutečné BLE tag_id, nebo interně generované unknown_* jméno.
active_tracks = {}

# Krátkodobé buffery syrových dat rozdělené podle senzoru.
# Do těchto bufferů zapisuje listen_raw_sensors() a čte z nich perform_fusion_loop().
sensor_buffers = {
    "radar_1": [],
    "radar_2": [],
    "ble_1": [],
    "ble_2": [],
}

# Protože současně běží MQTT listener i fusion smyčka, přístup k bufferům chráníme lockem.
buffer_lock = asyncio.Lock()


def triangulate_ble(angle1_deg, angle2_deg):
    """Vrátí odhad polohy BLE tagu z dvojice azimutů.

    Každá BLE kotva nám dává pouze směr, nikoli vzdálenost.
    Z jednoho měření tedy nevzniká bod, ale paprsek:

        P1 + t * d1
        P2 + s * d2

    kde:
    - P1, P2 jsou známé pozice kotev,
    - d1, d2 jsou směrové vektory odvozené z úhlů,
    - t, s jsou neznámé vzdálenosti podél paprsku.

    Hledáme průsečík obou paprsků. Pokud jsou směry téměř rovnoběžné,
    je jmenovatel soustavy skoro nulový a triangulace je numericky nestabilní.
    V takovém případě vracíme None.
    """
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
    """Spočítá teoretický BLE azimut pro objekt na pozici (obj_x, obj_y).

    Tato funkce se používá při kontrole identity. Pokud radar vidí objekt
    na určitém místě v mapě, BLE kotva by ho také měla vidět přibližně
    pod odpovídajícím úhlem.
    """
    cfg = SENSORS[sensor_id]
    dx = obj_x - cfg["x"]
    dy = obj_y - cfg["y"]
    angle_deg = math.degrees(math.atan2(dy, dx))
    return (angle_deg - cfg["rotation"] + 360) % 360


def average_angles(angles_deg):
    """Vypočítá kruhový průměr úhlů.

    Obyčejný aritmetický průměr na úhlech nefunguje.
    Například průměr 359° a 1° nesmí být 180°, ale 0°.

    Proto každý úhel převedeme na bod na jednotkové kružnici,
    sečteme jeho sinusovou a kosinusovou složku a výsledný směr
    přepočítáme zpět přes atan2.
    """
    if not angles_deg:
        return None

    sin_sum = sum(math.sin(math.radians(angle)) for angle in angles_deg)
    cos_sum = sum(math.cos(math.radians(angle)) for angle in angles_deg)
    return (math.degrees(math.atan2(sin_sum, cos_sum)) + 360) % 360


def find_matching_tag(center_x, center_y, ble_data_1, ble_data_2, active_tracks_keys):
    """Najde nejpravděpodobnější BLE tag pro radarový shluk.

    Vstupem je střed radarového clusteru a dostupná BLE data z obou kotev.
    Kandidáty hodnotíme dvoustupňově:

    1. Fyzická kontrola:
       Pokud máme úhly z obou BLE kotev, triangulujeme odhad místa tagu.
       Když je tento odhad příliš daleko od radarové polohy, kandidáta hned vyřadíme.

    2. Úhlová kontrola:
       Porovnáváme naměřený BLE azimut s úhlem, který by kotva měla vidět,
       kdyby tag skutečně patřil k radarovému clusteru.

    Výsledkem je kandidát s nejmenší průměrnou úhlovou chybou.
    """

    # Lokální pomocná verze kruhového průměru pro zpracování dat konkrétního tagu.
    def avg_angles(angles):
        if not angles:
            return None
        sin_sum = sum(math.sin(math.radians(angle)) for angle in angles)
        cos_sum = sum(math.cos(math.radians(angle)) for angle in angles)
        return (math.degrees(math.atan2(sin_sum, cos_sum)) + 360) % 360

    # Pro každý tag si sesbíráme všechny azimuty zvlášť z ble_1 a ble_2.
    tag_azimuths = {}

    for row in ble_data_1:
        tag = row[2]
        if tag not in tag_azimuths:
            tag_azimuths[tag] = {"az1": [], "az2": []}
        tag_azimuths[tag]["az1"].append(row[4])

    for row in ble_data_2:
        tag = row[2]
        if tag not in tag_azimuths:
            tag_azimuths[tag] = {"az1": [], "az2": []}
        tag_azimuths[tag]["az2"].append(row[4])

    exp_1 = calculate_expected_angle(center_x, center_y, "ble_1")
    exp_2 = calculate_expected_angle(center_x, center_y, "ble_2")

    # Sem se dostanou pouze kandidáti, kteří projdou fyzickou i úhlovou kontrolou.
    candidates = []

    for tag, az_data in tag_azimuths.items():
        # Tag už přiřazený jiné aktivní stopě nechceme znovu použít.
        if tag in active_tracks_keys:
            continue

        avg_az1 = avg_angles(az_data["az1"])
        avg_az2 = avg_angles(az_data["az2"])

        # Pokud máme oba úhly, zkusíme nejprve fyzickou triangulaci tagu.
        # Když vyjde tag výrazně jinde než radarový objekt, kandidát nemá smysl.
        if avg_az1 is not None and avg_az2 is not None:
            tag_pos = triangulate_ble(avg_az1, avg_az2)
            if tag_pos:
                dist = math.hypot(center_x - tag_pos[0], center_y - tag_pos[1])
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

        # Úhlový limit je záměrně volnější, protože BLE měření je šumové
        # a při rychlém pohybu nebo částečném zakrytí nemusí přesně sedět.
        if avg_diff < 80.0:
            candidates.append({"tag": tag, "diff": avg_diff})

    if not candidates:
        return "unknown", 0.5, None

    # Z možných kandidátů vybereme ten s nejmenší průměrnou úhlovou chybou.
    candidates.sort(key=lambda item: item["diff"])
    return candidates[0]["tag"], 0.9, candidates


async def listen_raw_sensors():
    """Sbírá syrové MQTT zprávy a třídí je do bufferů podle senzoru.

    Tato coroutine nic nepočítá. Jejím jediným úkolem je udělat z MQTT streamu
    krátkodobou paměť posledních radarových a BLE měření, kterou si pak
    periodicky odebírá fusion smyčka.
    """
    while True:
        try:
            async with aiomqtt.Client("127.0.0.1") as client:
                await client.subscribe("sensors/raw/#")
                print("Fusion: Listening to raw sensors on MQTT topic sensors/raw/#")

                async for message in client.messages:
                    topic = str(message.topic)
                    data = json.loads(message.payload.decode())

                    # Každá zpráva se pouze vloží do správného bufferu.
                    # Samotné zpracování probíhá až v přesně řízeném fusion kroku.
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
    """Hlavní fusion smyčka běžící v periodě 150 ms."""
    await db_handler.connect()

    while True:
        try:
            async with aiomqtt.Client("127.0.0.1") as mqtt_client:
                while True:
                    await asyncio.sleep(0.15)
                    current_time = time.time()

                    async with buffer_lock:
                        # Radarové body spotřebujeme okamžitě v tomto kroku.
                        # BLE měření necháváme žít déle, protože BLE může mít jinou cadence
                        # a krátký výpadek by jinak okamžitě rozbil už přiřazenou identitu.
                        r1 = [(d["x"], d["y"], d["z"]) for d in sensor_buffers["radar_1"]]
                        r2 = [(d["x"], d["y"], d["z"]) for d in sensor_buffers["radar_2"]]

                        valid_b1 = [d for d in sensor_buffers["ble_1"] if current_time - d["timestamp"] <= 1.0]
                        valid_b2 = [d for d in sensor_buffers["ble_2"] if current_time - d["timestamp"] <= 1.0]

                        b1 = [
                            (0, d["timestamp"], d.get("tag_id", "unknown"), d["rssi"], d["azimuth"])
                            for d in valid_b1
                        ]
                        b2 = [
                            (0, d["timestamp"], d.get("tag_id", "unknown"), d["rssi"], d["azimuth"])
                            for d in valid_b2
                        ]

                        sensor_buffers["radar_1"].clear()
                        sensor_buffers["radar_2"].clear()
                        sensor_buffers["ble_1"] = valid_b1
                        sensor_buffers["ble_2"] = valid_b2

                    all_radar_points = r1 + r2
                    final_fused_batch = []
                    fused_output_for_web = []

                    # KROK 1: Predikce všech existujících stop.
                    #
                    # Nové radarové clustery nepřiřazujeme ke staré pozici z minulého kroku,
                    # ale k pozici predikované Kalmanovým filtrem.
                    # Tím je párování stabilnější při pohybu objektu.
                    track_ids = list(active_tracks.keys())
                    coasting_tracks = set()

                    for track in active_tracks.values():
                        track.predict()
                        track.age += 0.15

                    # KROK 2: Shlukování radarových bodů.
                    #
                    # Radar neposílá rovnou "objekty", ale množinu bodů odrazu.
                    # DBSCAN z nich vytvoří shluky, které zjednodušeně reprezentují osoby / vozíky / cíle.
                    # Z každého shluku bereme těžiště jako radarové měření objektu.
                    clusters = []
                    if len(all_radar_points) >= 3:
                        radar_points = np.array(all_radar_points, dtype=float)
                        clustering = DBSCAN(eps=0.5, min_samples=2).fit(radar_points)
                        labels = clustering.labels_

                        for cluster_id in set(labels):
                            if cluster_id == -1:
                                continue

                            class_member_mask = labels == cluster_id
                            xyz = radar_points[class_member_mask]
                            cx, cy, cz = np.mean(xyz, axis=0)
                            clusters.append((cx, cy, cz))

                    # KROK 3A: První průchod přes tracky.
                    #
                    # Tady se jen snažíme každé stopě najít nejbližší radarový cluster
                    # a případně stopu zbrzdit, když radar dočasně zmizel.
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
                            # "Tření" je stabilizační trik:
                            # stopa bez radarové podpory nezmizí hned, ale zároveň se jí brzdí rychlost,
                            # aby se samovolně nevzdalovala od reality.
                            track.state[2] *= 0.5
                            track.state[3] *= 0.5

                    # KROK 3B: Hlavní párování a práce s identitou.
                    #
                    # V této části rozhodujeme:
                    # - zda unknown stopa dostane konkrétní tag,
                    # - zda pojmenovaná stopa stále odpovídá svému BLE tagu,
                    # - nebo zda má být degradována zpět na unknown.
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

                        if best_idx == -1:
                            continue

                        matched_clusters.add(best_idx)
                        rx, ry, rz = clusters[best_idx]

                        if tid in coasting_tracks:
                            continue

                        track.update(rx, ry)
                        track.current_z = float(rz)

                        # Unknown track: zkusíme ji povýšit na konkrétní tag.
                        if str(tid).startswith("unknown"):
                            new_tag_id, conf, _ = find_matching_tag(rx, ry, b1, b2, active_tracks.keys())
                            if new_tag_id != "unknown" and new_tag_id not in renames.values():
                                renames[tid] = new_tag_id

                        # Pojmenovaný track: ověřujeme, zda tag stále fyzicky odpovídá radarové stopě.
                        else:
                            my_b1_angles = [row[4] for row in b1 if row[2] == tid]
                            my_b2_angles = [row[4] for row in b2 if row[2] == tid]

                            avg_1 = average_angles(my_b1_angles)
                            avg_2 = average_angles(my_b2_angles)
                            dropped = False

                            # Hlavní metoda detekce "zahozeného tagu":
                            # triangulujeme BLE polohu tagu a měříme vzdálenost od radarové stopy.
                            if avg_1 is not None and avg_2 is not None:
                                tag_pos = triangulate_ble(avg_1, avg_2)
                                if tag_pos:
                                    tx, ty = tag_pos
                                    dist = math.hypot(rx - tx, ry - ty)
                                    if dist > 1.0:
                                        dropped = True

                            # Záložní metoda:
                            # pokud máme úhel jen z jedné kotvy, triangulace nejde,
                            # proto aspoň kontrolujeme, zda úhel není zcela mimo očekávaný směr.
                            else:
                                exp_1 = calculate_expected_angle(rx, ry, "ble_1")
                                exp_2 = calculate_expected_angle(rx, ry, "ble_2")
                                diff_1 = abs((avg_1 - exp_1 + 180) % 360 - 180) if avg_1 is not None else 0
                                diff_2 = abs((avg_2 - exp_2 + 180) % 360 - 180) if avg_2 is not None else 0

                                if (avg_1 is not None and diff_1 > 45.0) or (
                                    avg_2 is not None and diff_2 > 45.0
                                ):
                                    dropped = True

                            if dropped:
                                renames[tid] = f"unknown_{int(time.time() * 1000)}_drop"

                    # Přejmenování provádíme až po iteraci, aby se active_tracks neměnil během průchodu.
                    for old_tid, new_tid in renames.items():
                        active_tracks[new_tid] = active_tracks.pop(old_tid)
                        if old_tid in coasting_tracks:
                            coasting_tracks.remove(old_tid)
                            coasting_tracks.add(new_tid)

                    # KROK 4: Založení nových stop.
                    #
                    # Každý cluster, který se nepodařilo přiřadit ke starému tracku,
                    # považujeme za nový objekt v mapě.
                    for i, (rx, ry, rz) in enumerate(clusters):
                        if i in matched_clusters:
                            continue

                        tag_id, confidence, _ = find_matching_tag(rx, ry, b1, b2, active_tracks.keys())

                        if tag_id == "unknown" or tag_id in active_tracks:
                            tag_id = f"unknown_{int(time.time() * 1000)}_{i}"
                            confidence = 0.5

                        active_tracks[tag_id] = KalmanObject(rx, ry, dt=0.15)
                        active_tracks[tag_id].update(rx, ry)
                        active_tracks[tag_id].current_z = float(rz)

                    # KROK 5: Příprava snapshotu pro frontend a databázi.
                    #
                    # Frontend potřebuje:
                    # - pozici,
                    # - confidence,
                    # - opacity pro efekt vyblednutí při výpadku.
                    #
                    # Databáze ukládá už vyfiltrovaný stav celé scény v čase.
                    for tid, track in active_tracks.items():
                        smooth_x = float(track.state[0])
                        smooth_y = float(track.state[1])
                        smooth_z = getattr(track, "current_z", 0.92)

                        conf = 0.9 if track.age == 0.0 else 0.5
                        opacity = max(0.0, 1.0 - (track.age / 4.0))

                        final_fused_batch.append((time.time(), tid, smooth_x, smooth_y, smooth_z, conf))
                        fused_output_for_web.append(
                            {
                                "tag_id": tid,
                                "x": smooth_x,
                                "y": smooth_y,
                                "z": smooth_z,
                                "confidence": conf,
                                "opacity": opacity,
                            }
                        )

                    # KROK 6: Mazání mrtvých stop.
                    #
                    # Stopu nemažeme okamžitě při prvním výpadku.
                    # Necháme ji několik sekund "dožít", aby:
                    # - frontend mohl objekt plynule vyblednout,
                    # - krátký dropout nezničil hned identitu.
                    stale_ids = [tid for tid, track in active_tracks.items() if track.age > 4.0]
                    for tid in stale_ids:
                        del active_tracks[tid]

                    # Výstup posíláme průběžně i pro prázdnou scénu.
                    # Díky tomu frontend nezamrzne na posledních známých objektech.
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
    # Obě části běží souběžně:
    # - listener plní buffery,
    # - fusion_loop je periodicky zpracovává.
    print("--- FUSION ENGINE + KALMAN 3D + TRIANGULATION (MQTT ENABLED) ---")
    await asyncio.gather(listen_raw_sensors(), perform_fusion_loop())


if __name__ == "__main__":
    asyncio.run(main_fusion())
