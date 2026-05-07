"""Online fuzni vrstva radarovych a BLE dat.

Vstupem jsou syrova mereni z MQTT topicu `sensors/raw/#`. Radar uz prichazi
prevedeny do globalnich souradnic mistnosti, BLE prichazi jako identita tagu
a azimut/elevace z jednotlivych kotev.

Vystupem je jeden pravidelne publikovany JSON snapshot do `sensors/fused`.
Dashboard potom nemusi znat detaily triangulace, clusteringu ani parovani.

Aktualni verze neni plny multi-target tracker. Je to prakticka online
heuristika s lehkym Kalman vyhlazenim na vystupu:

- BLE tag se trianguluje z dvojice 3D smeru.
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
    from config import (
        BLE_CONFIGS,
        DB_BATCH_SIZE,
        DB_FLUSH_SECONDS,
        MAP_VIEW_X_MAX,
        MAP_VIEW_X_MIN,
        MAP_VIEW_Y_MAX,
        MAP_VIEW_Y_MIN,
        MQTT_HOST,
        TEST_AREA_X_MAX,
        TEST_AREA_X_MIN,
        TEST_AREA_Y_MAX,
        TEST_AREA_Y_MIN,
        TEST_AREA_Z_MAX,
        TEST_AREA_Z_MIN,
    )
    from db_handler import AsyncDBHandler
    from kalman_filter import KalmanObject
    from run_context import get_current_run_id
except ImportError:
    from .config import (
        BLE_CONFIGS,
        DB_BATCH_SIZE,
        DB_FLUSH_SECONDS,
        MAP_VIEW_X_MAX,
        MAP_VIEW_X_MIN,
        MAP_VIEW_Y_MAX,
        MAP_VIEW_Y_MIN,
        MQTT_HOST,
        TEST_AREA_X_MAX,
        TEST_AREA_X_MIN,
        TEST_AREA_Y_MAX,
        TEST_AREA_Y_MIN,
        TEST_AREA_Z_MAX,
        TEST_AREA_Z_MIN,
    )
    from .db_handler import AsyncDBHandler
    from .kalman_filter import KalmanObject
    from .run_context import get_current_run_id

RAW_RADAR_HISTORY_SECONDS = 0.4
MAX_RAW_RADAR_HISTORY_POINTS = 700
MAX_RADAR_POINTS_IN_MQTT_PAYLOAD = 250
FUSED_PUBLISH_INTERVAL_SECONDS = 0.05
MQTT_RECONNECT_SECONDS = 2
# Prahy jsou zatim ladene pro malou 3x3m mistnost. Drzim je pohromade tady,
# aby bylo jasne, ktere konstanty meni chovani fuzni logiky.
RADAR_CLUSTER_DISTANCE = 0.45
RADAR_CLUSTER_MAX_DZ = 0.40
RADAR_CLUSTER_MIN_POINTS = 3
RADAR_BLE_PAIR_MAX_DISTANCE = 1.0
RADAR_BLE_PAIR_HOLD_SECONDS = 8.0
RADAR_BLE_REACQUIRE_DISTANCE = 0.8
RADAR_BLE_LOCK_MAX_DISTANCE = 1.35
RADAR_BLE_Z_WEIGHT = 2.0
RADAR_BLE_COAST_SECONDS = 2.0
BLE_TAG_TTL_SECONDS = 4.0
RADAR_BLE_CONFIDENCE_MIN = 0.72
RADAR_BLE_CONFIDENCE_MAX = 0.97
RADAR_BLE_LOCK_PENALTY = 0.
RADAR_BLE_COAST_CONFIDENCE = 0.68
RADAR_CLUSTER_CONFIDENCE_MIN = 0.45
RADAR_CLUSTER_CONFIDENCE_MAX = 0.85
MAX_BAD_MESSAGE_LOGS = 20
MAX_PAYLOAD_PREVIEW_CHARS = 240
BLE_DEBUG_BOUNDS_MIN = (MAP_VIEW_X_MIN, MAP_VIEW_Y_MIN, TEST_AREA_Z_MIN)
BLE_DEBUG_BOUNDS_MAX = (MAP_VIEW_X_MAX, MAP_VIEW_Y_MAX, max(TEST_AREA_Z_MAX, 3.0))
TRIANGULATION_BOUNDS_MIN = (TEST_AREA_X_MIN, TEST_AREA_Y_MIN, TEST_AREA_Z_MIN)
TRIANGULATION_BOUNDS_MAX = (TEST_AREA_X_MAX, TEST_AREA_Y_MAX, TEST_AREA_Z_MAX)
BLE_DEBUG_FALLBACK_RAY_LENGTH = math.sqrt(
    ((MAP_VIEW_X_MAX - MAP_VIEW_X_MIN) ** 2)
    + ((MAP_VIEW_Y_MAX - MAP_VIEW_Y_MIN) ** 2)
    + ((BLE_DEBUG_BOUNDS_MAX[2] - BLE_DEBUG_BOUNDS_MIN[2]) ** 2)
)
KALMAN_TRACKABLE_SOURCES = {"radar_ble", "radar_ble_coasting", "ble_only", "radar_cluster"}
KALMAN_PROCESS_NOISE = 0.035
KALMAN_CLUSTER_PROCESS_NOISE = 0.10
KALMAN_INITIAL_COVARIANCE = 0.35
KALMAN_CLUSTER_INITIAL_COVARIANCE = 0.45
KALMAN_Z_SMOOTHING_ALPHA = 0.26
KALMAN_MEASUREMENT_NOISE = {
    "radar_ble": 0.20,
    "radar_ble_coasting": 0.50,
    "ble_only": 0.75,
    "radar_cluster": 0.16,
}
KALMAN_TRACK_MAX_IDLE_SECONDS = 1.2
KALMAN_CLUSTER_MATCH_MAX_DISTANCE = 0.75
KALMAN_CLUSTER_TRACK_PREFIX = "RADAR_TRACK_"
FUSED_DB_SAMPLE_SECONDS = 0.25
FUSED_DB_FLUSH_SECONDS = DB_FLUSH_SECONDS
FUSED_DB_BATCH_SIZE = DB_BATCH_SIZE
FUSED_DB_RETRY_SECONDS = 5.0
bad_message_count = 0

# BLE geometrie musi odpovidat fyzickemu rozmisteni kotev v mistnosti.
SENSORS = {
    cfg["id"]: {
        "x": cfg["pos_x"],
        "y": cfg["pos_y"],
        "z": cfg["pos_z"],
        "facing_angle": cfg["rotation"],
    }
    for cfg in BLE_CONFIGS
    if cfg["id"] in ("ble_1", "ble_2")
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


def safe_float(value, default=0.0):
    """Prevede hodnotu na float tak, aby jeden spatny objekt nezastavil zapis DB."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_fused_db_rows(objects, timestamp):
    """Prevede vystupni fused objekty na radky pro tabulku fused_data."""
    rows = []

    for obj in objects:
        tag_id = str(obj.get("tag_id", "")).strip()
        if not tag_id:
            continue

        rows.append(
            (
                get_current_run_id(),
                timestamp,
                tag_id,
                safe_float(obj.get("x")),
                safe_float(obj.get("y")),
                safe_float(obj.get("z")),
                safe_float(obj.get("confidence")),
            )
        )

    return rows


def clamp(value, minimum, maximum):
    """Omezi hodnotu do pevneho intervalu."""
    return max(minimum, min(maximum, value))


def radar_ble_confidence(pair_distance, pair_mode):
    """Spocita duveru pro objekt potvrzeny radarem i BLE.

    Nejvyssi duveru ma tag, jehoz BLE triangulace lezi blizko radar clusteru.
    Na hrane povolene vzdalenosti confidence klesa, protoze parovani uz muze
    byt nahodne. Locked parovani drzim nize, protoze cast informace pochazi
    z pameti predchozich snimku.
    """
    normalized_distance = clamp(pair_distance / RADAR_BLE_PAIR_MAX_DISTANCE, 0.0, 1.0)
    confidence = RADAR_BLE_CONFIDENCE_MAX - (
        normalized_distance * (RADAR_BLE_CONFIDENCE_MAX - RADAR_BLE_CONFIDENCE_MIN)
    )

    if pair_mode == "locked":
        confidence -= RADAR_BLE_LOCK_PENALTY

    return round(clamp(confidence, RADAR_BLE_CONFIDENCE_MIN, RADAR_BLE_CONFIDENCE_MAX), 3)


def radar_ble_coasting_confidence(memory):
    """Vrati duveru pro kratky radar BLE coasting po vypadku radaru."""
    if not memory:
        return RADAR_BLE_COAST_CONFIDENCE

    last_confidence = safe_float(memory.get("last_confidence"), RADAR_BLE_CONFIDENCE_MIN)
    confidence = min(last_confidence - 0.04, RADAR_BLE_COAST_CONFIDENCE)
    return round(clamp(confidence, 0.60, RADAR_BLE_COAST_CONFIDENCE), 3)


def radar_cluster_confidence(point_count):
    """Spocita duveru anonymniho radar clusteru podle poctu bodu.

    Bez BLE identity to nikdy nepovazuji za stoprocentni objekt. Vice bodu
    znamena stabilnejsi radarovou detekci, ale horni limit zustava pod 1.0.
    """
    confidence = RADAR_CLUSTER_CONFIDENCE_MIN + (point_count * 0.06)
    return round(clamp(confidence, RADAR_CLUSTER_CONFIDENCE_MIN, RADAR_CLUSTER_CONFIDENCE_MAX), 3)


def kalman_measurement_noise(source):
    """Vrati hladinu sumu mereni podle typu fused objektu."""
    return KALMAN_MEASUREMENT_NOISE.get(source, KALMAN_MEASUREMENT_NOISE["ble_only"])


def apply_kalman_tracking(objects, trackers, now, dt):
    """Vyhladi fused objekty a radar clusterum doplni stabilnejsi track ID."""
    dt = clamp(dt, 0.02, 0.20)
    named_trackers = trackers["named"]
    cluster_trackers = trackers["clusters"]
    observed_named_ids = set()
    observed_cluster_ids = set()

    for tracker_state in named_trackers.values():
        tracker_state["filter"].predict(dt)
    for tracker_state in cluster_trackers.values():
        tracker_state["filter"].predict(dt)

    for obj in objects:
        source = str(obj.get("source", "")).strip().lower()
        if source not in KALMAN_TRACKABLE_SOURCES:
            continue

        if source == "radar_cluster":
            best_tracker_id = None
            best_distance = None
            for tracker_id, tracker_state in cluster_trackers.items():
                if tracker_id in observed_cluster_ids:
                    continue

                tracker = tracker_state["filter"]
                distance = math.hypot(
                    safe_float(obj.get("x")) - float(tracker.x),
                    safe_float(obj.get("y")) - float(tracker.y),
                )
                if distance > KALMAN_CLUSTER_MATCH_MAX_DISTANCE:
                    continue

                if best_distance is None or distance < best_distance:
                    best_tracker_id = tracker_id
                    best_distance = distance

            measurement_noise = kalman_measurement_noise(source)
            if best_tracker_id is None:
                cluster_index = trackers["next_cluster_id"]
                trackers["next_cluster_id"] += 1
                best_tracker_id = f"{KALMAN_CLUSTER_TRACK_PREFIX}{cluster_index}"
                tracker = KalmanObject(
                    tag_id=best_tracker_id,
                    x0=safe_float(obj.get("x")),
                    y0=safe_float(obj.get("y")),
                    z0=safe_float(obj.get("z")),
                    dt=dt,
                    process_noise=KALMAN_CLUSTER_PROCESS_NOISE,
                    measurement_noise=measurement_noise,
                    initial_covariance=KALMAN_CLUSTER_INITIAL_COVARIANCE,
                    z_smoothing_alpha=KALMAN_Z_SMOOTHING_ALPHA,
                )
                cluster_trackers[best_tracker_id] = {"filter": tracker, "last_seen": now}
            else:
                tracker = cluster_trackers[best_tracker_id]["filter"]
                tracker.set_process_noise(KALMAN_CLUSTER_PROCESS_NOISE)
                tracker.set_measurement_noise(measurement_noise)
                tracker.update(
                    safe_float(obj.get("x")),
                    safe_float(obj.get("y")),
                    safe_float(obj.get("z")),
                )
                cluster_trackers[best_tracker_id]["last_seen"] = now

            observed_cluster_ids.add(best_tracker_id)
            obj["tag_id"] = best_tracker_id
            obj["x"] = round(float(cluster_trackers[best_tracker_id]["filter"].x), 4)
            obj["y"] = round(float(cluster_trackers[best_tracker_id]["filter"].y), 4)
            obj["z"] = round(float(cluster_trackers[best_tracker_id]["filter"].z), 4)
            continue

        tag_id = str(obj.get("tag_id", "")).strip()
        if not tag_id:
            continue

        measurement_noise = kalman_measurement_noise(source)
        tracker_state = named_trackers.get(tag_id)

        if not tracker_state:
            tracker = KalmanObject(
                tag_id=tag_id,
                x0=safe_float(obj.get("x")),
                y0=safe_float(obj.get("y")),
                z0=safe_float(obj.get("z")),
                dt=dt,
                process_noise=KALMAN_PROCESS_NOISE,
                measurement_noise=measurement_noise,
                initial_covariance=KALMAN_INITIAL_COVARIANCE,
                z_smoothing_alpha=KALMAN_Z_SMOOTHING_ALPHA,
            )
            tracker_state = {"filter": tracker, "last_seen": now}
            named_trackers[tag_id] = tracker_state
        else:
            tracker = tracker_state["filter"]
            tracker.set_process_noise(KALMAN_PROCESS_NOISE)
            tracker.set_measurement_noise(measurement_noise)
            tracker.update(
                safe_float(obj.get("x")),
                safe_float(obj.get("y")),
                safe_float(obj.get("z")),
            )
            tracker_state["last_seen"] = now

        observed_named_ids.add(tag_id)
        obj["x"] = round(float(tracker_state["filter"].x), 4)
        obj["y"] = round(float(tracker_state["filter"].y), 4)
        obj["z"] = round(float(tracker_state["filter"].z), 4)

    named_trackers_to_remove = [
        tag_id
        for tag_id, tracker_state in named_trackers.items()
        if tag_id not in observed_named_ids and now - tracker_state.get("last_seen", now) > KALMAN_TRACK_MAX_IDLE_SECONDS
    ]
    for tag_id in named_trackers_to_remove:
        named_trackers.pop(tag_id, None)

    cluster_trackers_to_remove = [
        tag_id
        for tag_id, tracker_state in cluster_trackers.items()
        if tag_id not in observed_cluster_ids and now - tracker_state.get("last_seen", now) > KALMAN_TRACK_MAX_IDLE_SECONDS
    ]
    for tag_id in cluster_trackers_to_remove:
        cluster_trackers.pop(tag_id, None)

    return objects


async def ensure_fused_db_ready(fusion_db_handler, last_retry_at):
    """Pripravi DB spojeni pro fused_data a pri vypadku ho zkousi obnovit."""
    now = time.time()
    if now - last_retry_at < FUSED_DB_RETRY_SECONDS:
        return False, last_retry_at

    try:
        await fusion_db_handler.connect()
        await fusion_db_handler.init_tables()
        print("Fusion DB: fused_data zapis je pripraveny.")
        return True, now
    except Exception as exc:
        print(f"Fusion DB: databaze neni dostupna, dalsi pokus za {FUSED_DB_RETRY_SECONDS}s: {exc}")
        return False, now


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
        missing = [key for key in ("tag_id", "azimuth", "elevation") if key not in data]
        if missing:
            raise ValueError(f"ble_1 payload missing keys: {', '.join(missing)}")
        return "ble_1"

    if "ble_2" in topic:
        missing = [key for key in ("tag_id", "azimuth", "elevation") if key not in data]
        if missing:
            raise ValueError(f"ble_2 payload missing keys: {', '.join(missing)}")
        return "ble_2"

    raise ValueError(f"unsupported raw topic: {topic}")


def normalize_ble_tag_id(tag_id):
    """Sjednoti BLE ID, aby stejny tag nevznikl dvakrat kvuli velikosti pismen."""
    return str(tag_id).strip().upper()


def vector_length(vector):
    return math.sqrt(sum(component * component for component in vector))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def subtract(a, b):
    return tuple(x - y for x, y in zip(a, b))


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def scale(vector, factor):
    return tuple(component * factor for component in vector)


def point_distance_3d(a, b, z_weight=RADAR_BLE_Z_WEIGHT):
    dx = safe_float(a.get("x")) - safe_float(b.get("x"))
    dy = safe_float(a.get("y")) - safe_float(b.get("y"))
    dz = safe_float(a.get("z")) - safe_float(b.get("z"))
    return math.sqrt((dx * dx) + (dy * dy) + (z_weight * dz * dz))


def ble_direction_vector(sensor, measurement):
    """Prevede azimut a elevaci z BLE kotvy na globalni 3D smerovy vektor."""
    yaw = math.radians(sensor["facing_angle"] - safe_float(measurement["azimuth"]))
    elevation = math.radians(safe_float(measurement["elevation"]))
    cos_elevation = math.cos(elevation)
    vector = (
        cos_elevation * math.cos(yaw),
        cos_elevation * math.sin(yaw),
        math.sin(elevation),
    )
    length = vector_length(vector)
    if length < 1e-6:
        return None
    return tuple(component / length for component in vector)


def ray_box_exit_distance(origin, direction, bounds_min=BLE_DEBUG_BOUNDS_MIN, bounds_max=BLE_DEBUG_BOUNDS_MAX):
    """Vrati vzdalenost k prvnimu pruseciku paprsku s hranou debug boxu."""
    best_t = None

    for axis in range(3):
        component = direction[axis]
        if abs(component) < 1e-6:
            continue

        boundary = bounds_max[axis] if component > 0 else bounds_min[axis]
        t = (boundary - origin[axis]) / component
        if t <= 0:
            continue

        hit = add(origin, scale(direction, t))
        if all(bounds_min[i] - 1e-6 <= hit[i] <= bounds_max[i] + 1e-6 for i in range(3)):
            if best_t is None or t < best_t:
                best_t = t

    return best_t


def build_ble_debug_rays(sensor_id, measurements):
    """Prevede raw BLE azimut/elevaci na globalni debug paprsky pro dashboard."""
    sensor = SENSORS.get(sensor_id)
    if not sensor:
        return []

    origin = (sensor["x"], sensor["y"], sensor["z"])
    rays = []

    for tag_id, measurement in sorted(measurements.items()):
        direction = ble_direction_vector(sensor, measurement)
        if not direction:
            continue

        distance = ray_box_exit_distance(origin, direction)
        if distance is None:
            distance = BLE_DEBUG_FALLBACK_RAY_LENGTH

        endpoint = add(origin, scale(direction, distance))
        rays.append(
            {
                "tag_id": tag_id,
                "sensor_id": sensor_id,
                "sensor_x": origin[0],
                "sensor_y": origin[1],
                "sensor_z": origin[2],
                "x": endpoint[0],
                "y": endpoint[1],
                "z": endpoint[2],
                "azimuth": safe_float(measurement.get("azimuth")),
                "elevation": safe_float(measurement.get("elevation")),
            }
        )

    return rays


def triangulate_3d(tag_id):
    """Vrati 3D odhad polohy tagu jako midpoint nejblizsiho priblizeni dvou paprsku."""
    b1 = shared_state["ble_tags"]["ble_1"].get(tag_id)
    b2 = shared_state["ble_tags"]["ble_2"].get(tag_id)

    if not b1 or not b2:
        return None

    sensor_1 = SENSORS.get("ble_1")
    sensor_2 = SENSORS.get("ble_2")
    if not sensor_1 or not sensor_2:
        return None

    origin_1 = (sensor_1["x"], sensor_1["y"], sensor_1["z"])
    origin_2 = (sensor_2["x"], sensor_2["y"], sensor_2["z"])
    direction_1 = ble_direction_vector(sensor_1, b1)
    direction_2 = ble_direction_vector(sensor_2, b2)
    if not direction_1 or not direction_2:
        return None

    w0 = subtract(origin_1, origin_2)
    a = dot(direction_1, direction_1)
    b = dot(direction_1, direction_2)
    c = dot(direction_2, direction_2)
    d = dot(direction_1, w0)
    e = dot(direction_2, w0)
    denominator = (a * c) - (b * b)
    if abs(denominator) < 1e-4:
        return None

    t1 = ((b * e) - (c * d)) / denominator
    t2 = ((a * e) - (b * d)) / denominator
    if t1 < 0 or t2 < 0:
        return None

    closest_1 = add(origin_1, scale(direction_1, t1))
    closest_2 = add(origin_2, scale(direction_2, t2))
    separation = vector_length(subtract(closest_1, closest_2))
    if separation > 1.0:
        return None

    midpoint = tuple((p1 + p2) / 2.0 for p1, p2 in zip(closest_1, closest_2))
    x, y, z = midpoint

    if (
        TRIANGULATION_BOUNDS_MIN[0] <= x <= TRIANGULATION_BOUNDS_MAX[0]
        and TRIANGULATION_BOUNDS_MIN[1] <= y <= TRIANGULATION_BOUNDS_MAX[1]
        and TRIANGULATION_BOUNDS_MIN[2] <= z <= TRIANGULATION_BOUNDS_MAX[2]
    ):
        return {"x": x, "y": y, "z": z}
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
                dz = abs(current_point["z"] - next_point["z"])
                if distance <= RADAR_CLUSTER_DISTANCE and dz <= RADAR_CLUSTER_MAX_DZ:
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
        coast_is_valid = memory and now - memory.get("last_radar_seen_at", 0) <= RADAR_BLE_COAST_SECONDS

        if memory_is_valid:
            # Pri platne pameti nehledame jen nejblizsi cluster k aktualni BLE
            # triangulaci. BLE umi poskakovat, proto nejdriv hledame cluster,
            # ktery navazuje na posledni radarovou polohu.
            remembered_cluster = None
            remembered_score = None
            for cluster in radar_clusters:
                if cluster["id"] in used_cluster_ids:
                    continue

                distance_from_memory = point_distance_3d(
                    cluster,
                    {
                        "x": memory.get("x", cluster["x"]),
                        "y": memory.get("y", cluster["y"]),
                        "z": memory.get("z", cluster.get("z", 0.0)),
                    },
                )
                if distance_from_memory > RADAR_BLE_REACQUIRE_DISTANCE:
                    continue

                same_id_bonus = 0 if cluster["id"] == memory.get("cluster_id") else 0.15
                score = distance_from_memory + same_id_bonus
                if remembered_score is None or score < remembered_score:
                    remembered_cluster = cluster
                    remembered_score = score

            if remembered_cluster and remembered_cluster["id"] not in used_cluster_ids:
                remembered_distance = point_distance_3d(
                    ble,
                    {
                        "x": remembered_cluster["x"],
                        "y": remembered_cluster["y"],
                        "z": remembered_cluster["z"],
                    },
                )
                if remembered_distance <= RADAR_BLE_LOCK_MAX_DISTANCE:
                    best_cluster = remembered_cluster
                    best_distance = remembered_distance
                    pair_mode = "locked"

        if not best_cluster:
            # Bez pameti spadneme na jednoduche nejblizsi parovani v povolenem
            # dosahu. To je startovni stav pro novy tag nebo pro tag po timeoutu.
            for cluster in radar_clusters:
                if cluster["id"] in used_cluster_ids:
                    continue

                distance = point_distance_3d(ble, cluster)
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
                "z": best_cluster["z"],
                "seen_at": now,
                "last_radar_seen_at": now,
                "last_confidence": radar_ble_confidence(best_distance, pair_mode),
            }
            confidence = shared_state["pair_memory"][tag_id]["last_confidence"]
            objects.append(
                {
                    "tag_id": tag_id,
                    "object_type": "radar_ble",
                    "source": "radar_ble",
                    "x": (best_cluster["x"] * 0.70) + (ble["x"] * 0.30),
                    "y": (best_cluster["y"] * 0.70) + (ble["y"] * 0.30),
                    "z": best_cluster["z"],
                    "confidence": confidence,
                    "radar_cluster_id": best_cluster["id"],
                    "points": best_cluster["points"],
                    "pair_distance": best_distance,
                    "pair_mode": pair_mode,
                }
            )
        else:
            if coast_is_valid:
                objects.append(
                    {
                        "tag_id": tag_id,
                        "object_type": "radar_ble_coasting",
                        "source": "radar_ble_coasting",
                        "x": (memory.get("x", ble["x"]) * 0.20) + (ble["x"] * 0.80),
                        "y": (memory.get("y", ble["y"]) * 0.20) + (ble["y"] * 0.80),
                        "z": memory.get("z", ble["z"]),
                        "confidence": radar_ble_coasting_confidence(memory),
                        "radar_cluster_id": memory.get("cluster_id"),
                        "pair_mode": "coasting",
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
                        "z": ble["z"],
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
                "confidence": radar_cluster_confidence(cluster["points"]),
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
                        data["tag_id"] = normalize_ble_tag_id(data["tag_id"])
                        data["_seen_at"] = time.time()
                        shared_state["ble_tags"]["ble_1"][data["tag_id"]] = data
                    elif source == "ble_2":
                        data["tag_id"] = normalize_ble_tag_id(data["tag_id"])
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
    """Publikuje snapshot pro app.py -> WebSocket -> index.html a uklada fused_data."""
    # Radarove body nedrzim jen v jednom frame, ale v kratke historii. Radar
    # vraci mrak bodu a clustering je stabilnejsi, kdyz ma par poslednich
    # mereni misto jedineho okamziku.
    radar_history = []
    fused_db_buffer = []
    db_ready = False
    last_db_retry = 0.0
    last_db_sample = 0.0
    last_db_flush = time.time()
    last_publish_at = time.time()
    kalman_trackers = {"named": {}, "clusters": {}, "next_cluster_id": 1}
    # asyncpg pool patri konkretnimu asyncio event loopu. Handler proto vzniká
    # az tady uvnitr publisheru, aby po restartu fusion loopu nepouzil stary
    # pool navazany na uz zavreny event loop.
    fusion_db_handler = AsyncDBHandler()

    while True:
        try:
            async with aiomqtt.Client(MQTT_HOST) as client:
                print("Fusion: Publikuji fused data na 'sensors/fused'")

                while True:
                    await asyncio.sleep(FUSED_PUBLISH_INTERVAL_SECONDS)
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
                        ble_1_ids = sorted(shared_state["ble_tags"]["ble_1"].keys())
                        ble_2_ids = sorted(shared_state["ble_tags"]["ble_2"].keys())
                        out_ble_1_raw = build_ble_debug_rays("ble_1", shared_state["ble_tags"]["ble_1"])
                        out_ble_2_raw = build_ble_debug_rays("ble_2", shared_state["ble_tags"]["ble_2"])
                        out_ble = []
                        common_tags = set(shared_state["ble_tags"]["ble_1"].keys()) & set(
                            shared_state["ble_tags"]["ble_2"].keys()
                        )
                        common_tag_ids = sorted(common_tags)
                        for tag_id in common_tags:
                            pos = triangulate_3d(tag_id)
                            if pos:
                                out_ble.append({"tag_id": tag_id, "x": pos["x"], "y": pos["y"], "z": pos["z"]})

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
                    out_radar_payload = out_radar[-MAX_RADAR_POINTS_IN_MQTT_PAYLOAD:]
                    out_clusters = cluster_radar_points(out_radar)
                    out_objects, paired_count = build_fused_objects(out_clusters, out_ble, now)
                    out_objects = apply_kalman_tracking(
                        out_objects,
                        kalman_trackers,
                        now,
                        now - last_publish_at,
                    )
                    last_publish_at = now

                    # Payload je navrzeny tak, aby frontend dostal zaroven
                    # surovy radar, clustery, vysledne objekty i diagnostiku.
                    # Pri ladeni pak nemusim menit backend jen kvuli grafu.
                    payload = json.dumps(
                        {
                            "type": "update",
                            "radar": out_radar_payload,
                            "radar_clusters": out_clusters,
                            "ble": out_ble,
                            "ble_1_raw": out_ble_1_raw,
                            "ble_2_raw": out_ble_2_raw,
                            "objects": out_objects,
                            "stats": {
                                "timestamp": now,
                                "new_radar_points": len(new_radar_points),
                                "radar_history_points": len(out_radar),
                                "radar_payload_points": len(out_radar_payload),
                                "radar_clusters": len(out_clusters),
                                "objects": len(out_objects),
                                "paired_radar_ble": paired_count,
                                "pair_max_distance": RADAR_BLE_PAIR_MAX_DISTANCE,
                                "pair_hold_seconds": RADAR_BLE_PAIR_HOLD_SECONDS,
                                "pair_reacquire_distance": RADAR_BLE_REACQUIRE_DISTANCE,
                                "pair_lock_max_distance": RADAR_BLE_LOCK_MAX_DISTANCE,
                                "pair_z_weight": RADAR_BLE_Z_WEIGHT,
                                "pair_coast_seconds": RADAR_BLE_COAST_SECONDS,
                                "ble_only_objects": sum(1 for obj in out_objects if obj["source"] == "ble_only"),
                                "radar_ble_coasting_objects": sum(
                                    1 for obj in out_objects if obj["source"] == "radar_ble_coasting"
                                ),
                                "radar_cluster_objects": sum(1 for obj in out_objects if obj["source"] == "radar_cluster"),
                                "ble_1_tags": ble_1_count,
                                "ble_2_tags": ble_2_count,
                                "common_ble_tags": len(common_tags),
                                "ble_1_ids": ble_1_ids,
                                "ble_2_ids": ble_2_ids,
                                "common_ble_ids": common_tag_ids,
                                "triangulated_ble": len(out_ble),
                            },
                        }
                    )
                    await client.publish("sensors/fused", payload)

                    if out_objects and not db_ready:
                        db_ready, last_db_retry = await ensure_fused_db_ready(fusion_db_handler, last_db_retry)

                    # Do DB neukladam kazdy 50ms frame. Dashboard potrebuje
                    # plynuly MQTT stream, ale databazi staci ridci vzorkovani
                    # v davkach, aby se zbytecne nezahltila pri delsim mereni.
                    if db_ready and out_objects and now - last_db_sample >= FUSED_DB_SAMPLE_SECONDS:
                        fused_db_buffer.extend(build_fused_db_rows(out_objects, now))
                        last_db_sample = now

                    should_flush = (
                        len(fused_db_buffer) >= FUSED_DB_BATCH_SIZE
                        or now - last_db_flush >= FUSED_DB_FLUSH_SECONDS
                    )
                    if db_ready and fused_db_buffer and should_flush:
                        try:
                            await fusion_db_handler.insert_batch("fused_data", fused_db_buffer)
                            fused_db_buffer.clear()
                            last_db_flush = now
                        except Exception as exc:
                            db_ready = False
                            last_db_retry = now
                            print(f"Fusion DB: zapis fused_data selhal, spojeni obnovim pozdeji: {exc}")
        except (aiomqtt.MqttError, OSError) as exc:
            print(f"Fusion publisher: MQTT/socket problem, retrying in {MQTT_RECONNECT_SECONDS}s: {exc}")
            await asyncio.sleep(MQTT_RECONNECT_SECONDS)


async def main():
    await asyncio.gather(mqtt_listener(), fused_publisher())


async def main_fusion():
    """Compatibility entry point used by main.py."""
    await main()


if __name__ == "__main__":
    asyncio.run(main())
