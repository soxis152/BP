"""Vyhodnoceni BLE, radaru a fuze proti OptiTrack ground truth."""

from __future__ import annotations

import argparse
from bisect import bisect_left
import csv
import json
import math
from pathlib import Path
import re
from statistics import mean, median
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = PROJECT_DIR.parent

for candidate in (PROJECT_ROOT, PROJECT_DIR, SCRIPT_DIR):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

try:
    from Four.experiment_tools.optitrack_xlsx import load_optitrack_take
except ImportError:
    try:
        from experiment_tools.optitrack_xlsx import load_optitrack_take
    except ImportError:
        from optitrack_xlsx import load_optitrack_take


OFFSET_SEARCH_IDENTITY_MARGIN_METERS = 0.20
DEFAULT_AXIS_X = "-x"
DEFAULT_AXIS_Y = "z"
DEFAULT_AXIS_Z = "y"
DEFAULT_YAW_DEG = -89.4461
DEFAULT_OFFSET_X = 2.6268
DEFAULT_OFFSET_Y = 3.8304
DEFAULT_OFFSET_Z = -0.1569
SUPPORTED_SOURCES = (
    "fusion",
    "ble",
    "radar",
    "radar1",
    "radar2",
    "ble1",
    "ble2",
    "radar12",
    "ble12",
    "radar1_ble1",
    "radar2_ble2",
    "radar1_ble12",
    "radar2_ble12",
    "radar12_ble12",
)
SOURCE_ALIASES = {
    "ble": "ble12",
    "radar": "radar12",
    "radary": "radar12",
    "ble kotvy": "ble12",
    "ble_kotvy": "ble12",
    "ble1 + radar1": "radar1_ble1",
    "ble1+radar1": "radar1_ble1",
    "radar1 + ble1": "radar1_ble1",
    "radar1+ble1": "radar1_ble1",
    "ble2 + radar2": "radar2_ble2",
    "ble2+radar2": "radar2_ble2",
    "radar2 + ble2": "radar2_ble2",
    "radar2+ble2": "radar2_ble2",
    "ble kotvy + radar1": "radar1_ble12",
    "ble kotvy+radar1": "radar1_ble12",
    "ble_kotvy+radar1": "radar1_ble12",
    "radar1 + ble kotvy": "radar1_ble12",
    "radar1+ble kotvy": "radar1_ble12",
    "radar1+ble_kotvy": "radar1_ble12",
    "ble kotvy + radar2": "radar2_ble12",
    "ble kotvy+radar2": "radar2_ble12",
    "ble_kotvy+radar2": "radar2_ble12",
    "radar2 + ble kotvy": "radar2_ble12",
    "radar2+ble kotvy": "radar2_ble12",
    "radar2+ble_kotvy": "radar2_ble12",
    "radary + ble kotvy": "radar12_ble12",
    "radary+ble kotvy": "radar12_ble12",
    "radary+ble_kotvy": "radar12_ble12",
    "ble kotvy + radary": "radar12_ble12",
    "ble kotvy+radary": "radar12_ble12",
    "ble_kotvy+radary": "radar12_ble12",
}
DEFAULT_SOURCES = "radar1,radar2,ble1,ble2,radar12,ble12,radar1_ble1,radar2_ble2,radar1_ble12,radar2_ble12,radar12_ble12"
RAW_RADAR_HISTORY_WINDOW_SECONDS = 0.4


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Porovna BLE, radar a fuzi s OptiTrack ground truth.")
    parser.add_argument("--input-dir", required=True, help="Adresar experimentu s fused.ndjson.")
    parser.add_argument("--xlsx", required=True, help="OptiTrack export (.xlsx nebo .csv).")
    parser.add_argument("--sheet", default=None, help="Nazev sheetu. Vychozi je prvni.")
    parser.add_argument("--axis-x", default=DEFAULT_AXIS_X, help="Mapovani OptiTrack osy na systemovou X.")
    parser.add_argument("--axis-y", default=DEFAULT_AXIS_Y, help="Mapovani OptiTrack osy na systemovou Y.")
    parser.add_argument("--axis-z", default=DEFAULT_AXIS_Z, help="Mapovani OptiTrack osy na systemovou Z.")
    parser.add_argument("--yaw-deg", type=float, default=DEFAULT_YAW_DEG, help="Dodatecna rotace OptiTracku v rovine XY.")
    parser.add_argument("--offset-x", type=float, default=DEFAULT_OFFSET_X, help="Posun X po prevodu os.")
    parser.add_argument("--offset-y", type=float, default=DEFAULT_OFFSET_Y, help="Posun Y po prevodu os.")
    parser.add_argument("--offset-z", type=float, default=DEFAULT_OFFSET_Z, help="Posun Z po prevodu os.")
    parser.add_argument("--tag-map", action="append", default=[], help="Mapovani TAG_ID=RigidBodyName.")
    parser.add_argument("--time-offset", type=float, default=None, help="Manualni posun casu senzoru proti OptiTracku.")
    parser.add_argument("--search-offset-start", type=float, default=-5.0, help="Start hledani casoveho posunu.")
    parser.add_argument("--search-offset-end", type=float, default=5.0, help="Konec hledani casoveho posunu.")
    parser.add_argument("--search-offset-step", type=float, default=0.05, help="Krok hledani casoveho posunu.")
    parser.add_argument("--search-samples", type=int, default=2000, help="Max pocet vzorku pro automaticke hledani offsetu.")
    parser.add_argument(
        "--sources",
        default=DEFAULT_SOURCES,
        help=(
            "Carkou oddeleny seznam zdroju k vyhodnoceni. "
            "Podporovano: fusion, ble/ble12, ble1, ble2, radar/radar12, radar1, radar2, "
            "radar1_ble1, radar2_ble2, radar1_ble12, radar2_ble12, radar12_ble12."
        ),
    )
    parser.add_argument(
        "--offset-source",
        default="fusion",
        help="Ktery tagovany zdroj pouzit pro automaticky odhad casoveho posunu.",
    )
    parser.add_argument(
        "--radar-match-max-distance",
        type=float,
        default=2.0,
        help="Max vzdalenost [m] pro sparovani radar clusteru s OptiTrack telosem.",
    )
    parser.add_argument(
        "--raw-radar-history-window",
        type=float,
        default=RAW_RADAR_HISTORY_WINDOW_SECONDS,
        help="Kolik sekund historie radarovych raw bodu pouzit pro radar1/radar2/radar12 evaluaci.",
    )
    parser.add_argument(
        "--plot-dir",
        default=None,
        help="Adresar pro PNG grafy. Vychozi je evaluation_plots v input-dir.",
    )
    parser.add_argument(
        "--plot-max-points",
        type=int,
        default=2500,
        help="Max pocet bodu v jednom grafu po decimaci.",
    )
    parser.add_argument("--skip-plots", action="store_true", help="Negenerovat PNG grafy.")
    parser.add_argument("--output", default=None, help="Kam ulozit evaluation JSON. Vychozi je evaluation.json v input-dir.")
    return parser.parse_args()


def sanitize_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(name).upper()).strip("_")


def parse_sources(raw_sources: str) -> list[str]:
    sources = []
    for item in raw_sources.split(","):
        source = SOURCE_ALIASES.get(item.strip().lower(), item.strip().lower())
        if not source:
            continue
        if source not in SUPPORTED_SOURCES:
            raise ValueError(
                f"Neznamy zdroj '{source}'. Podporovane zdroje: {', '.join(SUPPORTED_SOURCES)}"
            )
        if source not in sources:
            sources.append(source)
    if not sources:
        raise ValueError("Musis zadat alespon jeden zdroj v --sources.")
    return sources


def normalize_source_name(raw_source: str) -> str:
    source = SOURCE_ALIASES.get(raw_source.strip().lower(), raw_source.strip().lower())
    if source not in SUPPORTED_SOURCES:
        raise ValueError(
            f"Neznamy zdroj '{raw_source}'. Podporovane zdroje: {', '.join(SUPPORTED_SOURCES)}"
        )
    return source


def parse_tag_map(raw_items):
    mapping = {}
    for item in raw_items:
        if "=" not in item:
            raise ValueError(f"Neplatne --tag-map '{item}'. Pouzij TAG_ID=RigidBodyName.")
        tag_id, body_name = item.split("=", 1)
        mapping[tag_id.strip()] = body_name.strip()
    return mapping


def load_fused_records(fused_path: Path):
    records = []
    with fused_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            payload = json.loads(item["payload_text"])
            stats = payload.get("stats", {})
            records.append(
                {
                    "recorded_at": item["recorded_at"],
                    "payload_timestamp": item.get("payload_timestamp"),
                    "snapshot_timestamp": stats.get("timestamp", item["recorded_at"]),
                    "objects": payload.get("objects", []),
                    "ble": payload.get("ble", []),
                    "ble_1_raw": payload.get("ble_1_raw", []),
                    "ble_2_raw": payload.get("ble_2_raw", []),
                    "radar_clusters": payload.get("radar_clusters", []),
                }
            )
    if not records:
        raise ValueError(f"Soubor {fused_path} neobsahuje zadne fused zpravy.")
    return records


def load_raw_records(raw_path: Path):
    records = []
    with raw_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            payload = json.loads(item["payload_text"])
            records.append(
                {
                    "recorded_at": float(item["recorded_at"]),
                    "payload_timestamp": float(item.get("payload_timestamp") or payload.get("timestamp") or item["recorded_at"]),
                    "topic": str(item["topic"]),
                    "payload": payload,
                }
            )
    return records


def infer_tag_mapping(records, body_names, explicit_mapping):
    mapping = dict(explicit_mapping)
    body_by_upper = {name.upper(): name for name in body_names}
    body_by_sanitized = {sanitize_name(name): name for name in body_names}

    for record in records:
        for collection_name in ("objects", "ble", "ble_1_raw", "ble_2_raw"):
            for obj in record[collection_name]:
                tag_id = str(obj.get("tag_id", "")).strip()
                if not tag_id or tag_id in mapping:
                    continue

                upper = tag_id.upper()
                if upper in body_by_upper:
                    mapping[tag_id] = body_by_upper[upper]
                elif upper in body_by_sanitized:
                    mapping[tag_id] = body_by_sanitized[upper]
    return mapping


def build_ground_truth(take):
    trajectories = {}
    for body in take.rigid_bodies:
        times = []
        positions = []
        for frame in take.frames:
            if body.name in frame.bodies:
                x, y, z = frame.bodies[body.name]
                times.append(frame.time_seconds)
                positions.append((x, y, z))
        trajectories[body.name] = {"times": times, "positions": positions}
    return trajectories


def build_tagged_samples(records, tag_mapping, record_key, base_timestamp):
    total_snapshots = len(records)
    samples = []
    snapshots_by_tag = {tag_id: 0 for tag_id in tag_mapping}

    for record in records:
        relative_time = record["snapshot_timestamp"] - base_timestamp
        present_tags = set()
        for obj in record[record_key]:
            tag_id = str(obj.get("tag_id", "")).strip()
            if tag_id not in tag_mapping:
                continue
            present_tags.add(tag_id)
            samples.append(
                {
                    "tag_id": tag_id,
                    "body_name": tag_mapping[tag_id],
                    "relative_time": relative_time,
                    "x": float(obj.get("x", 0.0)),
                    "y": float(obj.get("y", 0.0)),
                    "z": float(obj.get("z", 0.0)),
                    "confidence": float(obj.get("confidence", 0.0)),
                    "source_kind": record_key,
                }
            )
        for tag_id in present_tags:
            snapshots_by_tag[tag_id] += 1

    return {
        "kind": "tagged",
        "record_key": record_key,
        "samples": samples,
        "total_snapshots": total_snapshots,
        "snapshots_by_tag": snapshots_by_tag,
    }


def build_tagged_snapshot_series(records, tag_mapping, record_key, base_timestamp):
    snapshots = []
    snapshots_by_tag = {tag_id: 0 for tag_id in tag_mapping}

    for snapshot_index, record in enumerate(records):
        relative_time = record["snapshot_timestamp"] - base_timestamp
        candidates = []
        present_tags = set()
        for candidate_index, obj in enumerate(record[record_key]):
            tag_id = str(obj.get("tag_id", "")).strip()
            if tag_id not in tag_mapping:
                continue
            present_tags.add(tag_id)
            candidates.append(
                {
                    "candidate_id": f"{record_key}_{snapshot_index}_{candidate_index}",
                    "source_kind": record_key,
                    "tag_id": tag_id,
                    "body_name": tag_mapping[tag_id],
                    "x": float(obj.get("x", 0.0)),
                    "y": float(obj.get("y", 0.0)),
                    "z": float(obj.get("z", 0.0)),
                    "confidence": float(obj.get("confidence", 0.0)),
                }
            )
        for tag_id in present_tags:
            snapshots_by_tag[tag_id] += 1
        snapshots.append({"relative_time": relative_time, "candidates": candidates})

    return {
        "kind": "mixed",
        "snapshots": snapshots,
        "total_snapshots": len(snapshots),
        "snapshots_by_tag": snapshots_by_tag,
    }


def build_radar_snapshots(records, base_timestamp):
    snapshots = []
    for record in records:
        relative_time = record["snapshot_timestamp"] - base_timestamp
        clusters = []
        for index, cluster in enumerate(record["radar_clusters"]):
            clusters.append(
                {
                    "cluster_index": index,
                    "cluster_id": cluster.get("id") or f"cluster_{index}",
                    "x": float(cluster.get("x", 0.0)),
                    "y": float(cluster.get("y", 0.0)),
                    "z": float(cluster.get("z", 0.0)),
                    "points": int(cluster.get("points", 0)),
                    "confidence": float(cluster.get("confidence", 0.0)),
                }
            )
        snapshots.append({"relative_time": relative_time, "clusters": clusters})
    return {"kind": "radar", "snapshots": snapshots, "total_snapshots": len(snapshots)}


def build_raw_radar_snapshots_from_topics(fused_records, raw_records, topic_names, base_timestamp, history_window_seconds):
    radar_records = [
        record
        for record in raw_records
        if record["topic"] in topic_names
    ]
    radar_records.sort(key=lambda item: item["payload_timestamp"])

    snapshots = []
    left_index = 0
    right_index = 0
    total_records = len(radar_records)

    for snapshot_index, record in enumerate(fused_records):
        snapshot_timestamp = float(record["snapshot_timestamp"])
        window_start = snapshot_timestamp - history_window_seconds

        while left_index < total_records and radar_records[left_index]["payload_timestamp"] < window_start:
            left_index += 1
        while right_index < total_records and radar_records[right_index]["payload_timestamp"] <= snapshot_timestamp:
            right_index += 1

        clusters = []
        for candidate_index, raw_record in enumerate(radar_records[left_index:right_index]):
            payload = raw_record["payload"]
            clusters.append(
                {
                    "cluster_index": candidate_index,
                    "cluster_id": f"{raw_record['topic'].replace('/', '_')}_{snapshot_index}_{candidate_index}",
                    "x": float(payload.get("x", 0.0)),
                    "y": float(payload.get("y", 0.0)),
                    "z": float(payload.get("z", 0.0)),
                    "points": 1,
                    "confidence": float(payload.get("snr", 0.0)),
                    "source_topic": raw_record["topic"],
                }
            )

        snapshots.append(
            {
                "relative_time": snapshot_timestamp - base_timestamp,
                "clusters": clusters,
            }
        )

    return {"kind": "radar", "snapshots": snapshots, "total_snapshots": len(snapshots)}


def build_mixed_snapshots(*, total_snapshots, primary_snapshots, secondary_snapshots):
    snapshots = []
    for index in range(total_snapshots):
        candidates = []
        if index < len(primary_snapshots):
            candidates.extend(primary_snapshots[index].get("clusters", []))
            candidates.extend(primary_snapshots[index].get("candidates", []))
        if index < len(secondary_snapshots):
            candidates.extend(secondary_snapshots[index].get("clusters", []))
            candidates.extend(secondary_snapshots[index].get("candidates", []))

        relative_time = 0.0
        if index < len(primary_snapshots):
            relative_time = primary_snapshots[index]["relative_time"]
        elif index < len(secondary_snapshots):
            relative_time = secondary_snapshots[index]["relative_time"]

        snapshots.append({"relative_time": relative_time, "candidates": candidates})

    return {"kind": "mixed", "snapshots": snapshots, "total_snapshots": total_snapshots}


def interpolate_body_position(points, target_time):
    if not points:
        return None

    times = points["times"]
    positions = points["positions"]
    if target_time < times[0] or target_time > times[-1]:
        return None

    right_index = bisect_left(times, target_time)
    if right_index == 0:
        return positions[0]
    if right_index >= len(times):
        return positions[-1]

    left_time = times[right_index - 1]
    right_time = times[right_index]
    left_position = positions[right_index - 1]
    right_position = positions[right_index]
    if math.isclose(right_time, left_time):
        return left_position

    alpha = (target_time - left_time) / (right_time - left_time)
    return (
        left_position[0] + ((right_position[0] - left_position[0]) * alpha),
        left_position[1] + ((right_position[1] - left_position[1]) * alpha),
        left_position[2] + ((right_position[2] - left_position[2]) * alpha),
    )


def distance_3d(a, b):
    return math.sqrt(((a[0] - b[0]) ** 2) + ((a[1] - b[1]) ** 2) + ((a[2] - b[2]) ** 2))


def distance_xy(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    index = (len(ordered) - 1) * fraction
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return ordered[lower]
    alpha = index - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * alpha)


def summarize_errors(errors):
    if not errors:
        return {"count": 0}

    dist_3d = [item["error_3d_m"] for item in errors]
    dist_xy = [item["error_xy_m"] for item in errors]
    abs_z = [abs(item["error_z_m"]) for item in errors]

    return {
        "count": len(errors),
        "mean_error_3d_m": mean(dist_3d),
        "median_error_3d_m": median(dist_3d),
        "p95_error_3d_m": percentile(dist_3d, 0.95),
        "max_error_3d_m": max(dist_3d),
        "rmse_3d_m": math.sqrt(sum(value * value for value in dist_3d) / len(dist_3d)),
        "mean_error_xy_m": mean(dist_xy),
        "median_error_xy_m": median(dist_xy),
        "mean_abs_error_z_m": mean(abs_z),
        "median_abs_error_z_m": median(abs_z),
    }


def build_error_item(sample, assigned_position, gt_time):
    sensor_position = (sample["x"], sample["y"], sample["z"])
    return {
        "tag_id": sample["tag_id"],
        "body_name": sample["body_name"],
        "gt_time": gt_time,
        "sensor_time": sample["relative_time"],
        "confidence": sample.get("confidence", 0.0),
        "sensor_x_m": sample["x"],
        "sensor_y_m": sample["y"],
        "sensor_z_m": sample["z"],
        "gt_x_m": assigned_position[0],
        "gt_y_m": assigned_position[1],
        "gt_z_m": assigned_position[2],
        "error_x_m": sample["x"] - assigned_position[0],
        "error_y_m": sample["y"] - assigned_position[1],
        "error_z_m": sample["z"] - assigned_position[2],
        "error_xy_m": distance_xy(sensor_position, assigned_position),
        "error_3d_m": distance_3d(sensor_position, assigned_position),
    }


def evaluate_tagged_samples(samples, trajectories, time_offset, tag_mapping):
    errors = []
    per_tag_errors = {tag_id: [] for tag_id in tag_mapping}
    identity_mismatch_counts = {tag_id: 0 for tag_id in tag_mapping}

    for sample in samples:
        gt_time = sample["relative_time"] + time_offset
        assigned_points = trajectories.get(sample["body_name"], [])
        assigned_position = interpolate_body_position(assigned_points, gt_time)
        if assigned_position is None:
            continue

        fused_position = (sample["x"], sample["y"], sample["z"])
        assigned_error = distance_3d(fused_position, assigned_position)

        best_other_error = None
        for other_tag_id, other_body_name in tag_mapping.items():
            if other_tag_id == sample["tag_id"]:
                continue
            other_position = interpolate_body_position(trajectories.get(other_body_name, []), gt_time)
            if other_position is None:
                continue
            other_error = distance_3d(fused_position, other_position)
            if best_other_error is None or other_error < best_other_error:
                best_other_error = other_error

        error_item = build_error_item(sample, assigned_position, gt_time)
        errors.append(error_item)
        per_tag_errors[sample["tag_id"]].append(error_item)

        if best_other_error is not None and best_other_error + OFFSET_SEARCH_IDENTITY_MARGIN_METERS < assigned_error:
            identity_mismatch_counts[sample["tag_id"]] += 1

    return errors, per_tag_errors, identity_mismatch_counts


def evaluate_radar_snapshots(radar_snapshots, trajectories, time_offset, tag_mapping, max_distance):
    errors = []
    per_tag_errors = {tag_id: [] for tag_id in tag_mapping}
    matched_snapshots_by_tag = {tag_id: 0 for tag_id in tag_mapping}
    identity_mismatch_counts = {tag_id: 0 for tag_id in tag_mapping}

    for snapshot in radar_snapshots:
        gt_time = snapshot["relative_time"] + time_offset
        candidate_bodies = []
        for tag_id, body_name in tag_mapping.items():
            gt_position = interpolate_body_position(trajectories.get(body_name, []), gt_time)
            if gt_position is None:
                continue
            candidate_bodies.append((tag_id, body_name, gt_position))
        if not candidate_bodies or not snapshot["clusters"]:
            continue

        pair_candidates = []
        for cluster in snapshot["clusters"]:
            sensor_position = (cluster["x"], cluster["y"], cluster["z"])
            for tag_id, body_name, gt_position in candidate_bodies:
                distance = distance_3d(sensor_position, gt_position)
                if distance <= max_distance:
                    pair_candidates.append((distance, cluster["cluster_index"], cluster, tag_id, body_name, gt_position))

        pair_candidates.sort(key=lambda item: item[0])
        used_clusters = set()
        used_tags = set()

        for _, cluster_index, cluster, tag_id, body_name, gt_position in pair_candidates:
            if cluster_index in used_clusters or tag_id in used_tags:
                continue
            used_clusters.add(cluster_index)
            used_tags.add(tag_id)

            sample = {
                "tag_id": tag_id,
                "body_name": body_name,
                "relative_time": snapshot["relative_time"],
                "x": cluster["x"],
                "y": cluster["y"],
                "z": cluster["z"],
                "confidence": float(cluster.get("points", 0)),
            }
            error_item = build_error_item(sample, gt_position, gt_time)
            error_item["cluster_id"] = cluster["cluster_id"]
            error_item["cluster_points"] = cluster["points"]
            errors.append(error_item)
            per_tag_errors[tag_id].append(error_item)
            matched_snapshots_by_tag[tag_id] += 1

    return errors, per_tag_errors, identity_mismatch_counts, matched_snapshots_by_tag


def evaluate_mixed_snapshots(mixed_snapshots, trajectories, time_offset, tag_mapping, max_distance):
    errors = []
    per_tag_errors = {tag_id: [] for tag_id in tag_mapping}
    matched_snapshots_by_tag = {tag_id: 0 for tag_id in tag_mapping}
    identity_mismatch_counts = {tag_id: 0 for tag_id in tag_mapping}

    for snapshot in mixed_snapshots:
        gt_time = snapshot["relative_time"] + time_offset
        candidate_bodies = []
        for tag_id, body_name in tag_mapping.items():
            gt_position = interpolate_body_position(trajectories.get(body_name, []), gt_time)
            if gt_position is None:
                continue
            candidate_bodies.append((tag_id, body_name, gt_position))
        if not candidate_bodies or not snapshot["candidates"]:
            continue

        pair_candidates = []
        for candidate_index, candidate in enumerate(snapshot["candidates"]):
            sensor_position = (candidate["x"], candidate["y"], candidate["z"])
            tagged_candidate = candidate.get("tag_id") in tag_mapping and candidate.get("body_name")

            if tagged_candidate:
                tag_id = candidate["tag_id"]
                body_name = candidate["body_name"]
                gt_position = interpolate_body_position(trajectories.get(body_name, []), gt_time)
                if gt_position is None:
                    continue
                distance = distance_3d(sensor_position, gt_position)
                pair_candidates.append((distance, candidate_index, candidate, tag_id, body_name, gt_position))
                continue

            for tag_id, body_name, gt_position in candidate_bodies:
                distance = distance_3d(sensor_position, gt_position)
                if distance <= max_distance:
                    pair_candidates.append((distance, candidate_index, candidate, tag_id, body_name, gt_position))

        pair_candidates.sort(key=lambda item: item[0])
        used_candidates = set()
        used_tags = set()

        for _, candidate_index, candidate, tag_id, body_name, gt_position in pair_candidates:
            if candidate_index in used_candidates or tag_id in used_tags:
                continue
            used_candidates.add(candidate_index)
            used_tags.add(tag_id)

            sample = {
                "tag_id": tag_id,
                "body_name": body_name,
                "relative_time": snapshot["relative_time"],
                "x": candidate["x"],
                "y": candidate["y"],
                "z": candidate["z"],
                "confidence": float(candidate.get("confidence", 0.0)),
            }
            error_item = build_error_item(sample, gt_position, gt_time)
            error_item["source_kind"] = candidate.get("source_kind", "mixed")
            error_item["candidate_id"] = candidate.get("candidate_id") or candidate.get("cluster_id")
            errors.append(error_item)
            per_tag_errors[tag_id].append(error_item)
            matched_snapshots_by_tag[tag_id] += 1

    return errors, per_tag_errors, identity_mismatch_counts, matched_snapshots_by_tag


def estimate_time_offset(samples, trajectories, tag_mapping, start, end, step, max_samples):
    if not samples:
        return 0.0

    sample_step = max(1, len(samples) // max(1, max_samples))
    sampled = samples[::sample_step]

    best_offset = 0.0
    best_score = None
    current = start
    while current <= end + 1e-9:
        errors, _, _ = evaluate_tagged_samples(sampled, trajectories, current, tag_mapping)
        if errors:
            score = median(item["error_3d_m"] for item in errors)
            if best_score is None or score < best_score:
                best_score = score
                best_offset = current
        current += step

    return best_offset


def build_source_result(
    *,
    source_name,
    label,
    errors,
    per_tag_errors,
    tag_mapping,
    total_snapshots,
    snapshots_by_tag,
    identity_mismatch_counts,
):
    overall = summarize_errors(errors)
    per_tag_summary = {}
    for tag_id, tag_errors in per_tag_errors.items():
        tag_summary = summarize_errors(tag_errors)
        tag_summary["body_name"] = tag_mapping[tag_id]
        tag_summary["presence_ratio"] = (
            snapshots_by_tag.get(tag_id, 0) / total_snapshots if total_snapshots > 0 else 0.0
        )
        tag_summary["suspected_identity_mismatches"] = identity_mismatch_counts.get(tag_id, 0)
        per_tag_summary[tag_id] = tag_summary

    return {
        "source": source_name,
        "label": label,
        "snapshots": total_snapshots,
        "overall": overall,
        "per_tag": per_tag_summary,
    }


def write_source_plots(plot_dir, source_name, source_label, per_tag_errors, plot_max_points):
    plot_dir.mkdir(parents=True, exist_ok=True)
    plot_paths = {}

    for tag_id, tag_errors in per_tag_errors.items():
        if not tag_errors:
            continue

        ordered = sorted(tag_errors, key=lambda item: item["gt_time"])
        if len(ordered) > plot_max_points:
            stride = max(1, math.ceil(len(ordered) / plot_max_points))
            ordered = ordered[::stride]

        times = [item["sensor_time"] for item in ordered]
        sensor_x = [item["sensor_x_m"] for item in ordered]
        sensor_y = [item["sensor_y_m"] for item in ordered]
        sensor_z = [item["sensor_z_m"] for item in ordered]
        gt_x = [item["gt_x_m"] for item in ordered]
        gt_y = [item["gt_y_m"] for item in ordered]
        gt_z = [item["gt_z_m"] for item in ordered]

        figure, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
        axis_rows = (
            ("X", sensor_x, gt_x),
            ("Y", sensor_y, gt_y),
            ("Z", sensor_z, gt_z),
        )
        for axis, (axis_name, sensor_values, gt_values) in zip(axes, axis_rows):
            axis.plot(times, sensor_values, label=f"{source_label} {axis_name}", linewidth=1.3, color="#2563eb")
            axis.plot(times, gt_values, label=f"OptiTrack {axis_name}", linewidth=1.3, linestyle="--", color="#d97706")
            axis.set_ylabel("[m]")
            axis.set_title(f"Axis {axis_name}: {source_label} vs OptiTrack {axis_name}")
            axis.grid(True, alpha=0.25)
            axis.legend(loc="best")

        body_name = ordered[0]["body_name"]
        figure.suptitle(f"{source_label} vs OptiTrack | {tag_id} -> {body_name}")
        axes[-1].set_xlabel("Time from source start [s]")
        figure.tight_layout()

        plot_path = plot_dir / f"{source_name}_{sanitize_name(tag_id)}.png"
        figure.savefig(plot_path, dpi=150, bbox_inches="tight")
        plt.close(figure)
        plot_paths[tag_id] = str(plot_path)

    return plot_paths


def print_source_summary(source_result):
    summary = source_result["overall"]
    label = source_result["label"]
    if summary.get("count", 0):
        print(
            f"Evaluation {label}: "
            f"count={summary['count']} "
            f"median_3d={summary['median_error_3d_m']:.3f}m "
            f"p95_3d={summary['p95_error_3d_m']:.3f}m "
            f"rmse_3d={summary['rmse_3d_m']:.3f}m"
        )
    else:
        print(f"Evaluation {label}: nenasel jsem zadne porovnatelne vzorky.")


def build_source_label(source_name: str) -> str:
    labels = {
        "fusion": "Fuze",
        "ble12": "2x BLE",
        "ble1": "BLE 1",
        "ble2": "BLE 2",
        "radar12": "2x Radar",
        "radar1": "Radar 1",
        "radar2": "Radar 2",
        "radar1_ble1": "BLE 1 + Radar 1",
        "radar2_ble2": "BLE 2 + Radar 2",
        "radar1_ble12": "2x BLE + Radar 1",
        "radar2_ble12": "2x BLE + Radar 2",
        "radar12_ble12": "2x Radar + 2x BLE",
    }
    return labels.get(source_name, source_name.upper())


def write_summary_csv(summary_csv_path: Path, requested_sources, source_results) -> None:
    summary_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "source_key",
                "label",
                "count",
                "mean_error_3d_m",
                "median_error_3d_m",
                "p95_error_3d_m",
                "max_error_3d_m",
                "rmse_3d_m",
                "mean_error_xy_m",
                "median_error_xy_m",
                "mean_abs_error_z_m",
                "median_abs_error_z_m",
                "mean_presence_ratio",
                "identity_mismatches_total",
            ],
        )
        writer.writeheader()

        for source_name in requested_sources:
            source_result = source_results[source_name]
            overall = source_result["overall"]
            per_tag = source_result["per_tag"]
            presence_values = [item.get("presence_ratio", 0.0) for item in per_tag.values() if item.get("count", 0) > 0]
            mismatch_total = sum(item.get("suspected_identity_mismatches", 0) for item in per_tag.values())
            writer.writerow(
                {
                    "source_key": source_name,
                    "label": source_result["label"],
                    "count": overall.get("count", 0),
                    "mean_error_3d_m": overall.get("mean_error_3d_m"),
                    "median_error_3d_m": overall.get("median_error_3d_m"),
                    "p95_error_3d_m": overall.get("p95_error_3d_m"),
                    "max_error_3d_m": overall.get("max_error_3d_m"),
                    "rmse_3d_m": overall.get("rmse_3d_m"),
                    "mean_error_xy_m": overall.get("mean_error_xy_m"),
                    "median_error_xy_m": overall.get("median_error_xy_m"),
                    "mean_abs_error_z_m": overall.get("mean_abs_error_z_m"),
                    "median_abs_error_z_m": overall.get("median_abs_error_z_m"),
                    "mean_presence_ratio": mean(presence_values) if presence_values else 0.0,
                    "identity_mismatches_total": mismatch_total,
                }
            )


def write_summary_json(summary_json_path: Path, requested_sources, source_results) -> None:
    summary_json_path.parent.mkdir(parents=True, exist_ok=True)
    summary_payload = {
        "sources": [
            {
                "source_key": source_name,
                "label": source_results[source_name]["label"],
                "overall": source_results[source_name]["overall"],
                "per_tag": source_results[source_name]["per_tag"],
            }
            for source_name in requested_sources
        ]
    }
    summary_json_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def escape_latex(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    escaped = str(text)
    for old, new in replacements.items():
        escaped = escaped.replace(old, new)
    return escaped


def format_metric(value) -> str:
    if value is None:
        return "--"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.3f}"


def latex_relative_path(path: Path) -> str:
    try:
        relative = path.resolve().relative_to(PROJECT_DIR.resolve())
        return relative.as_posix()
    except ValueError:
        return path.name


def source_sort_key(source_name: str, source_results) -> tuple[float, float]:
    overall = source_results[source_name]["overall"]
    median_3d = overall.get("median_error_3d_m")
    p95_3d = overall.get("p95_error_3d_m")
    return (
        float(median_3d) if median_3d is not None else float("inf"),
        float(p95_3d) if p95_3d is not None else float("inf"),
    )


def write_summary_latex(summary_tex_path: Path, requested_sources, source_results, *, ranked: bool = False) -> None:
    summary_tex_path.parent.mkdir(parents=True, exist_ok=True)
    source_order = list(requested_sources)
    if ranked:
        source_order = sorted(source_order, key=lambda item: source_sort_key(item, source_results))
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\small",
        r"\begin{tabular}{lrrrrrr}",
        r"\hline",
        r"Zdroj & N & Median 3D [m] & P95 3D [m] & RMSE 3D [m] & Median XY [m] & Median $|Z|$ [m] \\",
        r"\hline",
    ]

    for source_name in source_order:
        source_result = source_results[source_name]
        overall = source_result["overall"]
        lines.append(
            " & ".join(
                [
                    escape_latex(source_result["label"]),
                    format_metric(overall.get("count", 0)),
                    format_metric(overall.get("median_error_3d_m")),
                    format_metric(overall.get("p95_error_3d_m")),
                    format_metric(overall.get("rmse_3d_m")),
                    format_metric(overall.get("median_error_xy_m")),
                    format_metric(overall.get("median_abs_error_z_m")),
                ]
            )
            + r" \\"
        )

    lines.extend(
        [
            r"\hline",
            r"\end{tabular}",
            (
                r"\caption{Serazeny souhrn presnosti jednotlivych variant lokalizace vuci referencnimu systemu OptiTrack.}"
                if ranked else
                r"\caption{Souhrn presnosti jednotlivych variant lokalizace vuci referencnimu systemu OptiTrack.}"
            ),
            (
                r"\label{tab:optitrack_accuracy_ranked}"
                if ranked else
                r"\label{tab:optitrack_accuracy_summary}"
            ),
            r"\end{table}",
            "",
        ]
    )
    summary_tex_path.write_text("\n".join(lines), encoding="utf-8")


def write_figure_snippets(figures_tex_path: Path, comparison_plot_paths: dict[str, str]) -> None:
    figures_tex_path.parent.mkdir(parents=True, exist_ok=True)
    boxplot_path = comparison_plot_paths.get("error_3d_boxplot")
    cdf_path = comparison_plot_paths.get("error_3d_cdf")
    if not boxplot_path or not cdf_path:
        figures_tex_path.write_text("% Comparison plots were not generated.\n", encoding="utf-8")
        return

    boxplot_include = latex_relative_path(Path(boxplot_path))
    cdf_include = latex_relative_path(Path(cdf_path))
    lines = [
        r"\begin{figure}[htbp]",
        r"    \centering",
        rf"    \includegraphics[width=0.92\linewidth]{{{boxplot_include}}}",
        r"    \caption{Krabicovy graf prostorove chyby jednotlivych variant lokalizace vzhledem k referencnimu systemu OptiTrack.}",
        r"    \label{fig:optitrack_error_3d_boxplot}",
        r"\end{figure}",
        "",
        r"\begin{figure}[htbp]",
        r"    \centering",
        rf"    \includegraphics[width=0.92\linewidth]{{{cdf_include}}}",
        r"    \caption{Kumulativni distribucni funkce prostorove chyby pro jednotlive varianty lokalizace.}",
        r"    \label{fig:optitrack_error_3d_cdf}",
        r"\end{figure}",
        "",
    ]
    figures_tex_path.write_text("\n".join(lines), encoding="utf-8")


def join_labels_for_text(labels: list[str]) -> str:
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " a " + labels[-1]


def build_offset_text(time_offset: float, offset_source_label: str, source_results) -> str:
    if offset_source_label == "manual":
        return f"Casova synchronizace byla nastavena manualne s vyslednym posunem ${time_offset:.3f}\\,\\mathrm{{s}}$."
    if offset_source_label.startswith("estimated:"):
        offset_source = offset_source_label.split(":", 1)[1]
        source_label = source_results.get(offset_source, {}).get("label", build_source_label(offset_source))
        return (
            f"Casova synchronizace byla odhadnuta automaticky ze zdroje "
            f"\\texttt{{{escape_latex(source_label)}}} s vyslednym posunem "
            f"${time_offset:.3f}\\,\\mathrm{{s}}$."
        )
    return f"Pro vyhodnoceni byl pouzit casovy posun ${time_offset:.3f}\\,\\mathrm{{s}}$."


def write_accuracy_chapter_template(
    chapter_tex_path: Path,
    run_dir: Path,
    requested_sources,
    source_results,
    time_offset: float,
    offset_source_label: str,
    comparison_plot_paths: dict[str, str],
) -> None:
    chapter_tex_path.parent.mkdir(parents=True, exist_ok=True)
    ranked_sources = sorted(requested_sources, key=lambda item: source_sort_key(item, source_results))
    best_source = ranked_sources[0]
    second_source = ranked_sources[1] if len(ranked_sources) > 1 else best_source
    worst_source = ranked_sources[-1]
    best_summary = source_results[best_source]["overall"]
    second_summary = source_results[second_source]["overall"]
    worst_summary = source_results[worst_source]["overall"]
    summary_include = latex_relative_path(run_dir / "summary_metrics_table.tex")
    summary_ranked_include = latex_relative_path(run_dir / "summary_metrics_ranked_table.tex")
    figures_include = latex_relative_path(run_dir / "accuracy_figures.tex")
    detail_plot_dir = latex_relative_path(run_dir / "evaluation_plots")
    offset_text = build_offset_text(time_offset, offset_source_label, source_results)
    evaluated_labels = [escape_latex(source_results[source]["label"]) for source in requested_sources]

    lines = [
        r"\section{Vyhodnoceni presnosti vuci referencnimu systemu}",
        "",
        r"Cilem teto kapitoly je porovnat presnost jednotlivych variant lokalizace vuci referencnimu systemu OptiTrack. "
        rf"Vyhodnoceni bylo provedeno nad experimentem \texttt{{{escape_latex(run_dir.name)}}}. "
        + offset_text,
        "",
        r"\subsection{Vyhodnocovane varianty}",
        "",
        r"Porovnavane byly nasledujici varianty lokalizace: " + join_labels_for_text(evaluated_labels) + ".",
        "",
        r"\subsection{Pouzite metriky}",
        "",
        r"Jako hlavni metriky byly zvoleny median prostorove chyby, 95. percentil prostorove chyby a hodnota RMSE. "
        r"Doplnkove byly sledovany median horizontalni chyby v rovine XY a median absolutni chyby ve smeru osy Z. "
        r"Tyto metriky umoznuji hodnotit jak typickou presnost metody, tak i jeji chovani v horsich stavech.",
        "",
        r"\subsection{Souhrnne vysledky}",
        "",
        r"Tabulka~\ref{tab:optitrack_accuracy_summary} uvadi souhrn vyslednych metrik v puvodnim poradi variant. "
        r"Tabulka~\ref{tab:optitrack_accuracy_ranked} potom stejne vysledky radi podle medianu prostorove chyby.",
        "",
        rf"\input{{{summary_include}}}",
        "",
        rf"\input{{{summary_ranked_include}}}",
        "",
        r"Z hlediska medianu prostorove chyby dosahla nejlepsiho vysledku varianta "
        + escape_latex(source_results[best_source]["label"])
        + r" s hodnotou "
        + format_metric(best_summary.get("median_error_3d_m"))
        + r"\,\mathrm{m}. "
        r"Druhy nejlepsi vysledek poskytla varianta "
        + escape_latex(source_results[second_source]["label"])
        + r" s medianem "
        + format_metric(second_summary.get("median_error_3d_m"))
        + r"\,\mathrm{m}. "
        r"Naopak nejhorsi vysledek vykazala varianta "
        + escape_latex(source_results[worst_source]["label"])
        + r" s medianem "
        + format_metric(worst_summary.get("median_error_3d_m"))
        + r"\,\mathrm{m}.",
        "",
    ]
    if comparison_plot_paths:
        lines.extend(
            [
                r"\subsection{Distribuce chyby}",
                "",
                r"Pro lepsi interpretaci vysledku jsou na obr.~\ref{fig:optitrack_error_3d_boxplot} a "
                r"obr.~\ref{fig:optitrack_error_3d_cdf} uvedeny grafy rozdeleni prostorove chyby.",
                "",
                rf"\input{{{figures_include}}}",
                "",
                r"Krabicovy graf umoznuje rychle porovnat typickou chybu i rozsah hodnot jednotlivych variant, "
                r"zatimco kumulativni distribucni funkce ukazuje, jaka cast odhadu lezi pod zvolenou hranici chyby. "
                r"Z kombinace obou grafu je patrne, zda zlepseni vyplyva z posunu cele distribuce, nebo z omezeni odlehlych stavu.",
                "",
            ]
        )
    lines.extend(
        [
            r"\subsection{Interpretace}",
            "",
            r"Z vysledku je patrne, ze samotne BLE kotvy vykazuji oproti radarovym variantam vyrazne vyssi chybu. "
            r"Pridani druhe BLE kotvy vsak vede k citelnemu zlepseni oproti jednotlivym BLE vetvim. "
            r"Soucasne je videt, ze druhy radar poskytuje lepsi vysledky nez prvni radar, a to jak v medianu, tak v 95. percentilu chyby. "
            r"Nejpresnejsi vysledky nasledne poskytuje kombinace obou radarovych vetvi s obema BLE kotvami, "
            r"coz potvrzuje prinos multi-senzorove fuzni strategie.",
            "",
            r"\subsection{Doplnkova diagnostika}",
            "",
            r"Detailni casove prubehy po jednotlivych osach X, Y a Z jsou ulozeny v adresari "
            rf"\texttt{{{escape_latex(detail_plot_dir)}}}. "
            r"Tyto grafy slouzi zejmena pro diagnostiku systematickych odchylek v jednotlivych osach a nejsou proto pouzity jako hlavni srovnavaci vystup kapitoly.",
            "",
        ]
    )
    chapter_tex_path.write_text("\n".join(lines), encoding="utf-8")


def write_comparison_plots(plot_dir: Path, requested_sources, source_results, error_distributions) -> dict[str, str]:
    plot_dir.mkdir(parents=True, exist_ok=True)
    valid_sources = [
        source_name
        for source_name in requested_sources
        if error_distributions.get(source_name)
    ]
    if not valid_sources:
        return {}

    labels = [source_results[source_name]["label"] for source_name in valid_sources]
    distributions = [
        [item["error_3d_m"] for item in error_distributions[source_name]]
        for source_name in valid_sources
    ]

    boxplot_path = plot_dir / "error_3d_boxplot.png"
    figure, axis = plt.subplots(figsize=(max(11, len(valid_sources) * 1.1), 6.5))
    axis.boxplot(distributions, tick_labels=labels, showfliers=False)
    axis.set_ylabel("3D error [m]")
    axis.set_title("Srovnani 3D chyby proti OptiTracku")
    axis.grid(True, axis="y", alpha=0.25)
    plt.setp(axis.get_xticklabels(), rotation=25, ha="right")
    figure.tight_layout()
    figure.savefig(boxplot_path, dpi=150, bbox_inches="tight")
    plt.close(figure)

    cdf_path = plot_dir / "error_3d_cdf.png"
    figure, axis = plt.subplots(figsize=(11, 6.5))
    for label, values in zip(labels, distributions):
        ordered = sorted(values)
        cdf = [(index + 1) / len(ordered) for index in range(len(ordered))]
        axis.plot(ordered, cdf, linewidth=1.5, label=label)
    axis.set_xlabel("3D error [m]")
    axis.set_ylabel("CDF")
    axis.set_title("Kumulativni rozdeleni 3D chyby")
    axis.grid(True, alpha=0.25)
    axis.legend(loc="lower right", fontsize=9)
    figure.tight_layout()
    figure.savefig(cdf_path, dpi=150, bbox_inches="tight")
    plt.close(figure)

    return {
        "error_3d_boxplot": str(boxplot_path),
        "error_3d_cdf": str(cdf_path),
    }


def main() -> None:
    args = parse_args()
    requested_sources = parse_sources(args.sources)
    offset_source = normalize_source_name(args.offset_source)

    run_dir = Path(args.input_dir).resolve()
    fused_path = run_dir / "fused.ndjson"
    raw_path = run_dir / "raw.ndjson"
    records = load_fused_records(fused_path)
    raw_records = load_raw_records(raw_path) if raw_path.exists() else []
    fused_base_timestamp = min(record["snapshot_timestamp"] for record in records)
    raw_base_timestamp = min((record["payload_timestamp"] for record in raw_records), default=fused_base_timestamp)
    base_timestamp = min(fused_base_timestamp, raw_base_timestamp)

    take = load_optitrack_take(
        args.xlsx,
        sheet_name=args.sheet,
        axis_x=args.axis_x,
        axis_y=args.axis_y,
        axis_z=args.axis_z,
        yaw_degrees=args.yaw_deg,
        offset_x=args.offset_x,
        offset_y=args.offset_y,
        offset_z=args.offset_z,
    )
    trajectories = build_ground_truth(take)
    explicit_mapping = parse_tag_map(args.tag_map)
    tag_mapping = infer_tag_mapping(records, [body.name for body in take.rigid_bodies], explicit_mapping)
    if not tag_mapping:
        raise ValueError(
            "Nepodarilo se odvodit mapovani tagu na rigid body. "
            "Pouzij --tag-map TAG_ID=RigidBodyName."
        )

    source_inputs = {
        "fusion": build_tagged_samples(records, tag_mapping, "objects", base_timestamp),
        "ble12": build_tagged_samples(records, tag_mapping, "ble", base_timestamp),
        "ble1": build_tagged_samples(records, tag_mapping, "ble_1_raw", base_timestamp),
        "ble2": build_tagged_samples(records, tag_mapping, "ble_2_raw", base_timestamp),
        "radar12": build_raw_radar_snapshots_from_topics(
            records, raw_records, {"sensors/raw/radar_1", "sensors/raw/radar_2"}, base_timestamp, args.raw_radar_history_window
        ),
        "radar1": build_raw_radar_snapshots_from_topics(
            records, raw_records, {"sensors/raw/radar_1"}, base_timestamp, args.raw_radar_history_window
        ),
        "radar2": build_raw_radar_snapshots_from_topics(
            records, raw_records, {"sensors/raw/radar_2"}, base_timestamp, args.raw_radar_history_window
        ),
    }
    source_inputs["ble"] = source_inputs["ble12"]
    source_inputs["radar"] = source_inputs["radar12"]

    ble12_snapshots = build_tagged_snapshot_series(records, tag_mapping, "ble", base_timestamp)
    ble1_snapshots = build_tagged_snapshot_series(records, tag_mapping, "ble_1_raw", base_timestamp)
    ble2_snapshots = build_tagged_snapshot_series(records, tag_mapping, "ble_2_raw", base_timestamp)
    radar12_snapshots = source_inputs["radar12"]
    radar1_snapshots = source_inputs["radar1"]
    radar2_snapshots = source_inputs["radar2"]

    source_inputs["radar1_ble1"] = build_mixed_snapshots(
        total_snapshots=len(records),
        primary_snapshots=radar1_snapshots["snapshots"],
        secondary_snapshots=ble1_snapshots["snapshots"],
    )
    source_inputs["radar2_ble2"] = build_mixed_snapshots(
        total_snapshots=len(records),
        primary_snapshots=radar2_snapshots["snapshots"],
        secondary_snapshots=ble2_snapshots["snapshots"],
    )
    source_inputs["radar1_ble12"] = build_mixed_snapshots(
        total_snapshots=len(records),
        primary_snapshots=radar1_snapshots["snapshots"],
        secondary_snapshots=ble12_snapshots["snapshots"],
    )
    source_inputs["radar2_ble12"] = build_mixed_snapshots(
        total_snapshots=len(records),
        primary_snapshots=radar2_snapshots["snapshots"],
        secondary_snapshots=ble12_snapshots["snapshots"],
    )
    source_inputs["radar12_ble12"] = build_mixed_snapshots(
        total_snapshots=len(records),
        primary_snapshots=radar12_snapshots["snapshots"],
        secondary_snapshots=ble12_snapshots["snapshots"],
    )

    offset_samples = source_inputs[offset_source]["samples"]
    if not offset_samples and offset_source == "fusion":
        offset_source = "ble12"
        offset_samples = source_inputs[offset_source]["samples"]
    if not offset_samples:
        raise ValueError(
            f"Ve zdroji '{offset_source}' nejsou zadne tagovane vzorky pro odhad casoveho posunu."
        )

    if args.time_offset is None:
        time_offset = estimate_time_offset(
            offset_samples,
            trajectories,
            tag_mapping,
            args.search_offset_start,
            args.search_offset_end,
            args.search_offset_step,
            args.search_samples,
        )
        offset_source_label = f"estimated:{offset_source}"
    else:
        time_offset = args.time_offset
        offset_source_label = "manual"

    plot_dir = Path(args.plot_dir).resolve() if args.plot_dir else (run_dir / "evaluation_plots")
    source_results = {}
    error_distributions = {}

    for source_name in requested_sources:
        source_input = source_inputs[source_name]
        if source_input["kind"] == "tagged":
            errors, per_tag_errors, identity_mismatch_counts = evaluate_tagged_samples(
                source_input["samples"],
                trajectories,
                time_offset,
                tag_mapping,
            )
            source_result = build_source_result(
                source_name=source_name,
                label=build_source_label(source_name),
                errors=errors,
                per_tag_errors=per_tag_errors,
                tag_mapping=tag_mapping,
                total_snapshots=source_input["total_snapshots"],
                snapshots_by_tag=source_input["snapshots_by_tag"],
                identity_mismatch_counts=identity_mismatch_counts,
            )
        elif source_input["kind"] == "radar":
            errors, per_tag_errors, identity_mismatch_counts, matched_snapshots_by_tag = evaluate_radar_snapshots(
                source_input["snapshots"],
                trajectories,
                time_offset,
                tag_mapping,
                args.radar_match_max_distance,
            )
            source_result = build_source_result(
                source_name=source_name,
                label=build_source_label(source_name),
                errors=errors,
                per_tag_errors=per_tag_errors,
                tag_mapping=tag_mapping,
                total_snapshots=source_input["total_snapshots"],
                snapshots_by_tag=matched_snapshots_by_tag,
                identity_mismatch_counts=identity_mismatch_counts,
            )
            source_result["match_max_distance_m"] = args.radar_match_max_distance
        else:
            errors, per_tag_errors, identity_mismatch_counts, matched_snapshots_by_tag = evaluate_mixed_snapshots(
                source_input["snapshots"],
                trajectories,
                time_offset,
                tag_mapping,
                args.radar_match_max_distance,
            )
            source_result = build_source_result(
                source_name=source_name,
                label=build_source_label(source_name),
                errors=errors,
                per_tag_errors=per_tag_errors,
                tag_mapping=tag_mapping,
                total_snapshots=source_input["total_snapshots"],
                snapshots_by_tag=matched_snapshots_by_tag,
                identity_mismatch_counts=identity_mismatch_counts,
            )
            source_result["match_max_distance_m"] = args.radar_match_max_distance

        if not args.skip_plots:
            plot_paths = write_source_plots(
                plot_dir,
                source_name=source_name,
                source_label=source_result["label"],
                per_tag_errors=per_tag_errors,
                plot_max_points=args.plot_max_points,
            )
        else:
            plot_paths = {}

        for tag_id, summary in source_result["per_tag"].items():
            if tag_id in plot_paths:
                summary["plot_path"] = plot_paths[tag_id]
        source_result["plot_files"] = plot_paths
        source_results[source_name] = source_result
        error_distributions[source_name] = errors

    fusion_result = source_results.get("fusion", {"overall": {"count": 0}, "per_tag": {}})
    summary_csv_path = run_dir / "summary_metrics.csv"
    summary_json_path = run_dir / "summary_metrics.json"
    summary_tex_path = run_dir / "summary_metrics_table.tex"
    summary_ranked_tex_path = run_dir / "summary_metrics_ranked_table.tex"
    figures_tex_path = run_dir / "accuracy_figures.tex"
    chapter_template_path = run_dir / "accuracy_chapter_template.tex"
    write_summary_csv(summary_csv_path, requested_sources, source_results)
    write_summary_json(summary_json_path, requested_sources, source_results)
    comparison_plot_paths = write_comparison_plots(plot_dir, requested_sources, source_results, error_distributions) if not args.skip_plots else {}
    write_summary_latex(summary_tex_path, requested_sources, source_results)
    write_summary_latex(summary_ranked_tex_path, requested_sources, source_results, ranked=True)
    write_figure_snippets(figures_tex_path, comparison_plot_paths)
    write_accuracy_chapter_template(
        chapter_template_path,
        run_dir,
        requested_sources,
        source_results,
        time_offset,
        offset_source_label,
        comparison_plot_paths,
    )
    output = {
        "input_dir": str(run_dir),
        "xlsx": str(Path(args.xlsx).resolve()),
        "sheet": take.sheet_name,
        "axis_mapping": {"x": args.axis_x, "y": args.axis_y, "z": args.axis_z, "yaw_deg": args.yaw_deg},
        "offset_m": {"x": args.offset_x, "y": args.offset_y, "z": args.offset_z},
        "time_offset_seconds": time_offset,
        "time_offset_source": offset_source_label,
        "mapped_tags": tag_mapping,
        "sources_requested": requested_sources,
        "plot_dir": None if args.skip_plots else str(plot_dir),
        "summary_csv": str(summary_csv_path),
        "summary_json": str(summary_json_path),
        "summary_tex": str(summary_tex_path),
        "summary_ranked_tex": str(summary_ranked_tex_path),
        "figures_tex": str(figures_tex_path),
        "chapter_template_tex": str(chapter_template_path),
        "comparison_plots": comparison_plot_paths,
        "sources": source_results,
        # Zachovani zpetne kompatibility se starym vyhodnocenim fused vystupu.
        "fused_snapshots": source_inputs["fusion"]["total_snapshots"],
        "overall": fusion_result["overall"],
        "per_tag": fusion_result["per_tag"],
    }

    output_path = Path(args.output).resolve() if args.output else (run_dir / "evaluation.json")
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Evaluation: ulozeno do {output_path}")
    print(f"Evaluation: time_offset={time_offset:.3f}s ({offset_source_label})")
    print(f"Evaluation: souhrn CSV ulozen do {summary_csv_path}")
    print(f"Evaluation: souhrn JSON ulozen do {summary_json_path}")
    print(f"Evaluation: souhrn LaTeX tabulka ulozena do {summary_tex_path}")
    print(f"Evaluation: serazena LaTeX tabulka ulozena do {summary_ranked_tex_path}")
    print(f"Evaluation: LaTeX figure snippet ulozen do {figures_tex_path}")
    print(f"Evaluation: sablona kapitoly ulozena do {chapter_template_path}")
    if not args.skip_plots:
        print(f"Evaluation: grafy ulozeny do {plot_dir}")
        for plot_name, plot_path in comparison_plot_paths.items():
            print(f"Evaluation: {plot_name} -> {plot_path}")
    for source_name in requested_sources:
        print_source_summary(source_results[source_name])


if __name__ == "__main__":
    main()
