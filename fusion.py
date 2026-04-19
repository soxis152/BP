"""Online fuzni vrstva radarovych a BLE dat.

Vstupem jsou syrova mereni z MQTT topicu `sensors/raw/#`. Radar uz prichazi
prevedeny do globalnich souradnic mistnosti, BLE prichazi jako identita tagu
a azimut z jednotlivych kotev.

Vystupem je jeden pravidelne publikovany JSON snapshot do `sensors/fused`.
Dashboard potom nemusi znat detaily triangulace, clusteringu ani parovani.

Aktualni verze neni plny tracker s Kalman filtrem. Je to prakticka online
heuristika:

- BLE tag se trianguluje prusecikem dvou smeru.
- Radarove body se seskupi do shluku podle vzdalenosti.
- BLE pozice se sparuje s nejblizsim vhodnym radar clusterem.
- Kratka `pair_memory` pomaha udrzet identitu pri malych vypadcich a jitteru.
"""

import asyncio
import json
import math
import time

import aiomqtt

try:
    from config import MQTT_HOST
except ImportError:
    from .config import MQTT_HOST

RAW_RADAR_HISTORY_SECONDS = 2
MAX_RAW_RADAR_HISTORY_POINTS = 700
# Prahy jsou zatim ladene pro malou 3x3m mistnost. Drzim je pohromade tady,
# aby bylo jasne, ktere konstanty meni chovani fuzni logiky.
RADAR_CLUSTER_DISTANCE = 0.45
RADAR_CLUSTER_MIN_POINTS = 3
RADAR_BLE_PAIR_MAX_DISTANCE = 1.0
RADAR_BLE_PAIR_HOLD_SECONDS = 8.0
RADAR_BLE_REACQUIRE_DISTANCE = 0.8
RADAR_BLE_LOCK_MAX_DISTANCE = 1.35
BLE_TAG_TTL_SECONDS = 4.0
MAX_BAD_MESSAGE_LOGS = 20
MAX_PAYLOAD_PREVIEW_CHARS = 240
bad_message_count = 0

# BLE geometrie musi odpovidat fyzickemu rozmisteni kotev v mistnosti.
SENSORS = {
    "ble_1": {"x": 1.5, "y": 0.0, "facing_angle": 90},
    "ble_2": {"x": 0.0, "y": 1.5, "facing_angle": 0},
}

# Stav sdileny mezi MQTT listenerem a publisherem.
shared_state = {
    "radar_points": [],
    "ble_tags": {"ble_1": {}, "ble_2": {}},
    "pair_memory": {},
}
lock = asyncio.Lock()


def payload_preview(payload):
    """Vrati zkracenou ukazku payloadu pro diagnosticky log."""
    try:
        text = payload.decode("utf-8", errors="replace")
    except AttributeError:
        text = str(payload)

    if len(text) > MAX_PAYLOAD_PREVIEW_CHARS:
        return text[:MAX_PAYLOAD_PREVIEW_CHARS] + "..."
    return text


def validate_raw_message(topic, data):
    """Zkontroluje minimalni schema raw MQTT zpravy pred ulozenim do shared_state."""
    if not isinstance(data, dict):
        raise ValueError("payload is not a JSON object")

    if "radar" in topic:
        missing = [key for key in ("x", "y", "z") if key not in data]
        if missing:
            raise ValueError(f"radar payload missing keys: {', '.join(missing)}")
        return "radar"

    if "ble_1" in topic:
        missing = [key for key in ("tag_id", "azimuth") if key not in data]
        if missing:
            raise ValueError(f"ble_1 payload missing keys: {', '.join(missing)}")
        return "ble_1"

    if "ble_2" in topic:
        missing = [key for key in ("tag_id", "azimuth") if key not in data]
        if missing:
            raise ValueError(f"ble_2 payload missing keys: {', '.join(missing)}")
        return "ble_2"

    raise ValueError(f"unsupported raw topic: {topic}")


def triangulate(tag_id):
    """Vrati 2D prusecik smeru ze dvou BLE kotev pro jeden tag."""
    b1 = shared_state["ble_tags"]["ble_1"].get(tag_id)
    b2 = shared_state["ble_tags"]["ble_2"].get(tag_id)

    if not b1 or not b2: return None

    # u-blox azimut prevadim do souradne soustavy mistnosti.
    ang1 = math.radians(SENSORS["ble_1"]["facing_angle"] - b1["azimuth"])
    ang2 = math.radians(SENSORS["ble_2"]["facing_angle"] - b2["azimuth"])

    x1, y1 = SENSORS["ble_1"]["x"], SENSORS["ble_1"]["y"]
    x2, y2 = SENSORS["ble_2"]["x"], SENSORS["ble_2"]["y"]

    v1x, v1y = math.cos(ang1), math.sin(ang1)
    v2x, v2y = math.cos(ang2), math.sin(ang2)

    # Analyticky prusecik dvou parametrickych primek.
    det = v1x * v2y - v1y * v2x
    if abs(det) < 0.001: return None

    dx = x2 - x1
    dy = y2 - y1
    t1 = (dx * v2y - dy * v2x) / det

    if t1 < 0: return None

    x = x1 + t1 * v1x
    y = y1 + t1 * v1y

    if -0.5 <= x <= 3.5 and -0.5 <= y <= 3.5:
        return (x, y)
    return None


def cluster_radar_points(points):
    """Seskupi blizke radarove body a vrati stredu kazdeho shluku."""
    valid_points = [
        point
        for point in points
        if all(key in point for key in ("x", "y", "z"))
    ]
    visited = [False] * len(valid_points)
    clusters = []

    # Tohle je jednoducha flood-fill varianta clusteringu. Pro stovky bodu
    # v male mistnosti je O(n^2) porad v poradku a ma minimum zavislosti.
    for start_index, _ in enumerate(valid_points):
        if visited[start_index]:
            continue

        queue = [start_index]
        visited[start_index] = True
        cluster = []

        while queue:
            current_index = queue.pop()
            current_point = valid_points[current_index]
            cluster.append(current_point)

            for next_index, next_point in enumerate(valid_points):
                if visited[next_index]:
                    continue

                distance = math.hypot(
                    current_point["x"] - next_point["x"],
                    current_point["y"] - next_point["y"],
                )
                if distance <= RADAR_CLUSTER_DISTANCE:
                    visited[next_index] = True
                    queue.append(next_index)

        if len(cluster) < RADAR_CLUSTER_MIN_POINTS:
            continue

        clusters.append(
            {
                "id": f"radar_cluster_{len(clusters) + 1}",
                "x": sum(point["x"] for point in cluster) / len(cluster),
                "y": sum(point["y"] for point in cluster) / len(cluster),
                "z": sum(point["z"] for point in cluster) / len(cluster),
                "points": len(cluster),
            }
        )

    return clusters


def build_fused_objects(radar_clusters, ble_positions, now):
    """Sestavi objekty pro dashboard z radar clusteru a BLE triangulaci."""
    objects = []
    used_cluster_ids = set()
    paired_count = 0

    def has_active_memory(ble):
        memory = shared_state["pair_memory"].get(ble["tag_id"])
        return bool(memory and now - memory.get("seen_at", 0) <= RADAR_BLE_PAIR_HOLD_SECONDS)

    # BLE tagy s aktivni pameti parujeme jako prvni. Tim zmensujeme sanci,
    # ze jim novy tag "ukradne" cluster, se kterym byly spojene v minulem okne.
    for ble in sorted(ble_positions, key=lambda item: 0 if has_active_memory(item) else 1):
        best_cluster = None
        best_distance = None
        tag_id = ble["tag_id"]
        pair_mode = "live"
        memory = shared_state["pair_memory"].get(tag_id)
        memory_is_valid = memory and now - memory.get("seen_at", 0) <= RADAR_BLE_PAIR_HOLD_SECONDS

        if memory_is_valid:
            # Pri platne pameti nehledame jen nejblizsi cluster k aktualni BLE
            # triangulaci. BLE umi poskakovat, proto nejdriv hledame cluster,
            # ktery navazuje na posledni radarovou polohu.
            remembered_cluster = None
            remembered_score = None
            for cluster in radar_clusters:
                if cluster["id"] in used_cluster_ids:
                    continue

                distance_from_memory = math.hypot(
                    cluster["x"] - memory.get("x", cluster["x"]),
                    cluster["y"] - memory.get("y", cluster["y"]),
                )
                if distance_from_memory > RADAR_BLE_REACQUIRE_DISTANCE:
                    continue

                same_id_bonus = 0 if cluster["id"] == memory.get("cluster_id") else 0.15
                score = distance_from_memory + same_id_bonus
                if remembered_score is None or score < remembered_score:
                    remembered_cluster = cluster
                    remembered_score = score

            if remembered_cluster and remembered_cluster["id"] not in used_cluster_ids:
                remembered_distance = math.hypot(
                    ble["x"] - remembered_cluster["x"],
                    ble["y"] - remembered_cluster["y"],
                )
                if remembered_distance <= RADAR_BLE_LOCK_MAX_DISTANCE:
                    best_cluster = remembered_cluster
                    best_distance = remembered_distance
                    pair_mode = "locked"

        if not best_cluster and not memory_is_valid:
            # Bez pameti spadneme na jednoduche nejblizsi parovani v povolenem
            # dosahu. To je startovni stav pro novy tag nebo pro tag po timeoutu.
            for cluster in radar_clusters:
                if cluster["id"] in used_cluster_ids:
                    continue

                distance = math.hypot(ble["x"] - cluster["x"], ble["y"] - cluster["y"])
                if distance <= RADAR_BLE_PAIR_MAX_DISTANCE and (
                    best_distance is None or distance < best_distance
                ):
                    best_cluster = cluster
                    best_distance = distance
            pair_mode = "live"

        if best_cluster:
            used_cluster_ids.add(best_cluster["id"])
            paired_count += 1
            shared_state["pair_memory"][tag_id] = {
                "cluster_id": best_cluster["id"],
                "x": best_cluster["x"],
                "y": best_cluster["y"],
                "z": best_cluster.get("z", 0.8),
                "seen_at": now,
            }
            confidence = 0.95 if pair_mode == "live" else 0.80
            objects.append(
                {
                    "tag_id": tag_id,
                    "object_type": "radar_ble",
                    "source": "radar_ble",
                    "x": (best_cluster["x"] * 0.70) + (ble["x"] * 0.30),
                    "y": (best_cluster["y"] * 0.70) + (ble["y"] * 0.30),
                    "z": best_cluster.get("z", 0.8),
                    "confidence": confidence,
                    "radar_cluster_id": best_cluster["id"],
                    "points": best_cluster["points"],
                    "pair_distance": best_distance,
                    "pair_mode": pair_mode,
                }
            )
        else:
            if not memory_is_valid:
                shared_state["pair_memory"].pop(tag_id, None)
            objects.append(
                {
                    "tag_id": tag_id,
                    "object_type": "ble_only",
                    "source": "ble_only",
                    "x": ble["x"],
                    "y": ble["y"],
                    "z": 0.8,
                    "confidence": 0.60,
                }
            )

    for cluster in radar_clusters:
        # Nesparovane clustery nechavam ve vystupu jako radar-only objekty.
        # Je to dulezite pro ladeni: hned vidim, jestli radar neco vidi, ale
        # BLE k tomu nema identitu.
        if cluster["id"] in used_cluster_ids:
            continue
        objects.append(
            {
                "tag_id": cluster["id"],
                "object_type": "radar_cluster",
                "source": "radar_cluster",
                "x": cluster["x"],
                "y": cluster["y"],
                "z": cluster["z"],
                "confidence": min(1.0, 0.45 + (cluster["points"] * 0.08)),
                "points": cluster["points"],
            }
        )

    active_ble_ids = {ble["tag_id"] for ble in ble_positions}
    shared_state["pair_memory"] = {
        tag_id: memory
        for tag_id, memory in shared_state["pair_memory"].items()
        if tag_id in active_ble_ids and now - memory.get("seen_at", 0) <= RADAR_BLE_PAIR_HOLD_SECONDS
    }

    return objects, paired_count


async def mqtt_listener():
    """Prijima raw MQTT zpravy z ingestion vrstvy."""
    global bad_message_count
    print("Fusion: Čekám na MQTT data na 'sensors/raw/#'...")
    async with aiomqtt.Client(MQTT_HOST) as client:
        await client.subscribe("sensors/raw/#")
        async for message in client.messages:
            try:
                topic = str(message.topic)
                data = json.loads(message.payload.decode())
                source = validate_raw_message(topic, data)

                async with lock:
                    if source == "radar":
                        shared_state["radar_points"].append(data)
                    elif source == "ble_1":
                        data["_seen_at"] = time.time()
                        shared_state["ble_tags"]["ble_1"][data["tag_id"]] = data
                    elif source == "ble_2":
                        data["_seen_at"] = time.time()
                        shared_state["ble_tags"]["ble_2"][data["tag_id"]] = data
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
                bad_message_count += 1
                if bad_message_count <= MAX_BAD_MESSAGE_LOGS:
                    print(
                        "Fusion listener: bad raw MQTT message "
                        f"#{bad_message_count} on {message.topic}: {exc}; "
                        f"payload={payload_preview(message.payload)!r}"
                    )
                elif bad_message_count == MAX_BAD_MESSAGE_LOGS + 1:
                    print("Fusion listener: dalsi spatne raw MQTT zpravy uz potlacuji, aby log nebyl zahlceny.")


async def fused_publisher():
    """Publikuje snapshot pro app.py -> WebSocket -> index.html."""
    # Radarove body nedrzim jen v jednom frame, ale v kratke historii. Radar
    # vraci mrak bodu a clustering je stabilnejsi, kdyz ma par poslednich
    # mereni misto jedineho okamziku.
    radar_history = []

    while True:
        try:
            async with aiomqtt.Client(MQTT_HOST) as client:
                print("Fusion: Publikuji fused data na 'sensors/fused'")

                while True:
                    await asyncio.sleep(0.05)
                    now = time.time()

                    async with lock:
                        # Sdilene fronty se cisti atomicky pod lockem. Publisher
                        # si vezme aktualni davku a listener muze hned prijimat
                        # dalsi zpravy.
                        new_radar_points = list(shared_state["radar_points"])
                        shared_state["radar_points"].clear()

                        for sensor_id in ("ble_1", "ble_2"):
                            shared_state["ble_tags"][sensor_id] = {
                                tag_id: tag
                                for tag_id, tag in shared_state["ble_tags"][sensor_id].items()
                                if now - tag.get("_seen_at", tag.get("timestamp", now)) <= BLE_TAG_TTL_SECONDS
                            }

                        ble_1_count = len(shared_state["ble_tags"]["ble_1"])
                        ble_2_count = len(shared_state["ble_tags"]["ble_2"])
                        out_ble = []
                        common_tags = set(shared_state["ble_tags"]["ble_1"].keys()) & set(
                            shared_state["ble_tags"]["ble_2"].keys()
                        )
                        for tag_id in common_tags:
                            pos = triangulate(tag_id)
                            if pos:
                                out_ble.append({"tag_id": tag_id, "x": pos[0], "y": pos[1]})

                    for point in new_radar_points:
                        point = dict(point)
                        point["_seen_at"] = now
                        radar_history.append(point)

                    radar_history = [
                        point
                        for point in radar_history
                        if now - point.get("_seen_at", now) <= RAW_RADAR_HISTORY_SECONDS
                    ][-MAX_RAW_RADAR_HISTORY_POINTS:]

                    out_radar = [
                        {key: value for key, value in point.items() if key != "_seen_at"}
                        for point in radar_history
                    ]
                    out_clusters = cluster_radar_points(out_radar)
                    out_objects, paired_count = build_fused_objects(out_clusters, out_ble, now)

                    # Payload je navrzeny tak, aby frontend dostal zaroven
                    # surovy radar, clustery, vysledne objekty i diagnostiku.
                    # Pri ladeni pak nemusim menit backend jen kvuli grafu.
                    payload = json.dumps(
                        {
                            "type": "update",
                            "radar": out_radar,
                            "radar_clusters": out_clusters,
                            "ble": out_ble,
                            "objects": out_objects,
                            "stats": {
                                "timestamp": now,
                                "new_radar_points": len(new_radar_points),
                                "radar_history_points": len(out_radar),
                                "radar_clusters": len(out_clusters),
                                "objects": len(out_objects),
                                "paired_radar_ble": paired_count,
                                "pair_max_distance": RADAR_BLE_PAIR_MAX_DISTANCE,
                                "pair_hold_seconds": RADAR_BLE_PAIR_HOLD_SECONDS,
                                "pair_reacquire_distance": RADAR_BLE_REACQUIRE_DISTANCE,
                                "pair_lock_max_distance": RADAR_BLE_LOCK_MAX_DISTANCE,
                                "ble_only_objects": sum(1 for obj in out_objects if obj["source"] == "ble_only"),
                                "radar_cluster_objects": sum(1 for obj in out_objects if obj["source"] == "radar_cluster"),
                                "ble_1_tags": ble_1_count,
                                "ble_2_tags": ble_2_count,
                                "common_ble_tags": len(common_tags),
                                "triangulated_ble": len(out_ble),
                            },
                        }
                    )
                    await client.publish("sensors/fused", payload)
        except aiomqtt.MqttError:
            print("Fusion publisher: MQTT connection lost, retrying in 2s...")
            await asyncio.sleep(2)


async def main():
    await asyncio.gather(mqtt_listener(), fused_publisher())


async def main_fusion():
    """Compatibility entry point used by main.py."""
    await main()


if __name__ == "__main__":
    asyncio.run(main())
