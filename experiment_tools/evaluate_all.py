"""Vyhodnoti vsechny scenare proti OptiTrack CSV a ulozi JSON statistiky i JPG grafy."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import matplotlib
import numpy as np


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
    from Four.experiment_tools.scenario_pipeline_common import (
        DEFAULT_OPTITRACK_CSV,
        SCENARIO_TOPICS,
        resolve_run_dir,
        resolve_scenario_root,
        write_json,
    )
except ImportError:
    try:
        from experiment_tools.optitrack_xlsx import load_optitrack_take
        from experiment_tools.scenario_pipeline_common import (
            DEFAULT_OPTITRACK_CSV,
            SCENARIO_TOPICS,
            resolve_run_dir,
            resolve_scenario_root,
            write_json,
        )
    except ImportError:
        from optitrack_xlsx import load_optitrack_take
        from scenario_pipeline_common import (
            DEFAULT_OPTITRACK_CSV,
            SCENARIO_TOPICS,
            resolve_run_dir,
            resolve_scenario_root,
            write_json,
        )


DELAY_SEC = 7.391
OFFSET_X = 2.371
OFFSET_Y = 3.815
OFFSET_Z = 0.067
OPTITRACK_TIMEZONE = "Europe/Prague"
COLOR_OPTITRACK = "#5B8DB8"
COLOR_FUSION = "#E7A45B"
COLOR_ERROR = "#C96B6B"
COLOR_GRID = "#D7DEE8"
COLOR_TEXT = "#334155"
COLOR_NO_DATA = "#94A3B8"

TARGETS = {
    "Phantom4": {
        "tag_id": "20BA360ABBB8",
        "csv_position_columns": {"x": 5, "y": 6, "z": 7},
    },
    "Vysavac3": {
        "tag_id": "20BA360ABB32",
        "csv_position_columns": {"x": 11, "y": 12, "z": 13},
    },
}
BLE_ONLY_SCENARIOS = {
    "ble1": "ble_1_raw",
    "ble2": "ble_2_raw",
}
RADAR_ONLY_SCENARIOS = {"radar1", "radar2", "2x_radar"}
RADAR_MATCH_MAX_DISTANCE_M = 2.5


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vyhodnoti vsechny scenare proti OptiTrack CSV.")
    parser.add_argument(
        "--scenario-root",
        default=None,
        help="Root adresar se scenari. Vychozi: <run-dir>/scenario_splits.",
    )
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Zdrojovy experiment run dir. Pouzije se jen pro odvozeni vychoziho scenario rootu.",
    )
    parser.add_argument(
        "--optitrack-csv",
        default=str(DEFAULT_OPTITRACK_CSV),
        help="Cesta k referencnimu OptiTrack CSV souboru.",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=list(SCENARIO_TOPICS.keys()),
        help="Volitelny seznam scenaru k vyhodnoceni.",
    )
    return parser.parse_args(argv)


def parse_capture_start_timestamp(raw_value: str) -> float:
    start_dt = datetime.strptime(raw_value, "%Y-%m-%d %I.%M.%S.%f %p")
    try:
        return start_dt.replace(tzinfo=ZoneInfo(OPTITRACK_TIMEZONE)).timestamp()
    except ZoneInfoNotFoundError:
        return start_dt.replace(tzinfo=prague_fallback_timezone(start_dt)).timestamp()


def last_sunday(year: int, month: int) -> datetime:
    day = datetime(year, month + 1, 1) - timedelta(days=1) if month < 12 else datetime(year, month, 31)
    return day - timedelta(days=(day.weekday() + 1) % 7)


def prague_fallback_timezone(moment: datetime):
    dst_start = last_sunday(moment.year, 3).replace(hour=2, minute=0, second=0, microsecond=0)
    dst_end = last_sunday(moment.year, 10).replace(hour=3, minute=0, second=0, microsecond=0)
    if dst_start <= moment < dst_end:
        return timezone(timedelta(hours=2))
    return timezone(timedelta(hours=1))


def load_optitrack_reference(optitrack_csv: Path) -> dict[str, dict[str, np.ndarray]]:
    take = load_optitrack_take(
        optitrack_csv,
        axis_x="z",
        axis_y="x",
        axis_z="y",
        yaw_degrees=0.0,
        offset_x=OFFSET_X,
        offset_y=OFFSET_Y,
        offset_z=OFFSET_Z,
        selected_bodies=TARGETS.keys(),
    )

    capture_start_raw = take.metadata.get("Capture Start Time")
    if not capture_start_raw:
        raise ValueError("V OptiTrack CSV chybi metadata 'Capture Start Time'.")
    capture_start_ts = parse_capture_start_timestamp(capture_start_raw)

    reference = {}
    for target_name in TARGETS:
        times = []
        positions = []
        for frame in take.frames:
            position = frame.bodies.get(target_name)
            if position is None:
                continue
            times.append(capture_start_ts + frame.time_seconds + DELAY_SEC)
            positions.append(position)

        if not times:
            raise ValueError(f"V OptiTrack CSV nejsou zadna data pro objekt {target_name}.")

        time_array = np.asarray(times, dtype=float)
        position_array = np.asarray(positions, dtype=float)
        unique_times, unique_indices = np.unique(time_array, return_index=True)
        reference[target_name] = {
            "times": unique_times,
            "positions": position_array[unique_indices],
        }

    return reference


def load_fused_track(fused_path: Path, tag_id: str) -> tuple[np.ndarray, np.ndarray]:
    times = []
    positions = []

    with fused_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue

            record = json.loads(text)
            payload_text = record.get("payload_text")
            if payload_text is None:
                continue

            try:
                payload = json.loads(payload_text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Soubor {fused_path} ma neplatny payload_text na radku {line_number}: {exc}") from exc

            timestamp = float(
                record.get("payload_timestamp")
                or record.get("recorded_at")
                or payload.get("stats", {}).get("timestamp")
                or 0.0
            )
            for obj in payload.get("objects", []):
                if str(obj.get("tag_id", "")).strip().upper() != tag_id:
                    continue
                try:
                    x = float(obj["x"])
                    y = float(obj["y"])
                    z = float(obj["z"])
                except (KeyError, TypeError, ValueError):
                    continue
                times.append(timestamp)
                positions.append((x, y, z))
                break

    if not times:
        return np.asarray([], dtype=float), np.empty((0, 3), dtype=float)

    time_array = np.asarray(times, dtype=float)
    position_array = np.asarray(positions, dtype=float)
    unique_times, unique_indices = np.unique(time_array, return_index=True)
    return unique_times, position_array[unique_indices]


def load_fused_frames(fused_path: Path) -> list[tuple[float, dict]]:
    frames = []
    with fused_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            record = json.loads(text)
            payload_text = record.get("payload_text")
            if payload_text is None:
                continue
            try:
                payload = json.loads(payload_text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Soubor {fused_path} ma neplatny payload_text na radku {line_number}: {exc}") from exc
            timestamp = float(
                record.get("payload_timestamp")
                or record.get("recorded_at")
                or payload.get("stats", {}).get("timestamp")
                or 0.0
            )
            frames.append((timestamp, payload))
    return frames


def interpolate_reference(sensor_times: np.ndarray, reference: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    if sensor_times.size == 0:
        return np.empty((0, 3), dtype=float), np.asarray([], dtype=bool)

    ref_times = reference["times"]
    ref_positions = reference["positions"]
    valid = (sensor_times >= ref_times[0]) & (sensor_times <= ref_times[-1])
    interpolated = np.full((sensor_times.shape[0], 3), np.nan, dtype=float)

    if np.any(valid):
        for axis in range(3):
            interpolated[valid, axis] = np.interp(sensor_times[valid], ref_times, ref_positions[:, axis])

    return interpolated, valid


def interpolate_reference_at_timestamp(timestamp: float, reference: dict[str, np.ndarray]) -> np.ndarray | None:
    ref_times = reference["times"]
    if timestamp < ref_times[0] or timestamp > ref_times[-1]:
        return None
    values = [np.interp(timestamp, ref_times, reference["positions"][:, axis]) for axis in range(3)]
    return np.asarray(values, dtype=float)


def load_radar_tracks_by_matching(
    fused_path: Path,
    reference_tracks: dict[str, dict[str, np.ndarray]],
    target_order: list[str],
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    collected = {target_name: {"times": [], "positions": []} for target_name in target_order}
    frames = load_fused_frames(fused_path)

    for timestamp, payload in frames:
        detections = []
        for obj in payload.get("objects", []):
            if obj.get("source") != "radar_cluster":
                continue
            try:
                detections.append(np.asarray([float(obj["x"]), float(obj["y"]), float(obj["z"])], dtype=float))
            except (KeyError, TypeError, ValueError):
                continue

        if not detections:
            for cluster in payload.get("radar_clusters", []):
                try:
                    detections.append(np.asarray([float(cluster["x"]), float(cluster["y"]), float(cluster["z"])], dtype=float))
                except (KeyError, TypeError, ValueError):
                    continue

        if not detections:
            continue

        gt_positions = {}
        for target_name in target_order:
            gt_position = interpolate_reference_at_timestamp(timestamp, reference_tracks[target_name])
            if gt_position is not None:
                gt_positions[target_name] = gt_position

        if not gt_positions:
            continue

        candidate_pairs = []
        for detection_index, detection in enumerate(detections):
            for target_name, gt_position in gt_positions.items():
                distance = float(np.linalg.norm(detection - gt_position))
                if distance <= RADAR_MATCH_MAX_DISTANCE_M:
                    candidate_pairs.append((distance, detection_index, target_name))

        if not candidate_pairs:
            continue

        candidate_pairs.sort(key=lambda item: item[0])
        used_detections = set()
        used_targets = set()
        for distance, detection_index, target_name in candidate_pairs:
            if detection_index in used_detections or target_name in used_targets:
                continue
            used_detections.add(detection_index)
            used_targets.add(target_name)
            collected[target_name]["times"].append(timestamp)
            collected[target_name]["positions"].append(detections[detection_index])

    result = {}
    for target_name, payload in collected.items():
        if not payload["times"]:
            result[target_name] = (np.asarray([], dtype=float), np.empty((0, 3), dtype=float))
            continue
        times = np.asarray(payload["times"], dtype=float)
        positions = np.asarray(payload["positions"], dtype=float)
        unique_times, unique_indices = np.unique(times, return_index=True)
        result[target_name] = (unique_times, positions[unique_indices])
    return result


def compute_ble_ray_metrics(point: np.ndarray, origin: np.ndarray, endpoint: np.ndarray) -> tuple[float, float]:
    direction = endpoint - origin
    direction_norm = float(np.linalg.norm(direction))
    target_vector = point - origin
    target_norm = float(np.linalg.norm(target_vector))
    if direction_norm < 1e-9 or target_norm < 1e-9:
        return float("nan"), float("nan")

    direction_unit = direction / direction_norm
    target_unit = target_vector / target_norm
    projection = float(np.dot(target_vector, direction_unit))
    if projection < 0:
        closest_point = origin
    else:
        closest_point = origin + (projection * direction_unit)
    ray_distance = float(np.linalg.norm(point - closest_point))
    cosine = float(np.clip(np.dot(direction_unit, target_unit), -1.0, 1.0))
    angle_error_deg = float(np.degrees(np.arccos(cosine)))
    return ray_distance, angle_error_deg


def load_ble_only_metrics(
    fused_path: Path,
    raw_field_name: str,
    reference_track: dict[str, np.ndarray],
    tag_id: str,
) -> dict[str, np.ndarray]:
    timestamps = []
    ray_distances = []
    angle_errors = []

    for timestamp, payload in load_fused_frames(fused_path):
        gt_position = interpolate_reference_at_timestamp(timestamp, reference_track)
        if gt_position is None:
            continue

        ray_record = None
        for ray in payload.get(raw_field_name, []):
            if str(ray.get("tag_id", "")).strip().upper() == tag_id:
                ray_record = ray
                break
        if ray_record is None:
            continue

        try:
            origin = np.asarray(
                [float(ray_record["sensor_x"]), float(ray_record["sensor_y"]), float(ray_record["sensor_z"])],
                dtype=float,
            )
            endpoint = np.asarray(
                [float(ray_record["x"]), float(ray_record["y"]), float(ray_record["z"])],
                dtype=float,
            )
        except (KeyError, TypeError, ValueError):
            continue

        ray_distance, angle_error_deg = compute_ble_ray_metrics(gt_position, origin, endpoint)
        if np.isnan(ray_distance) or np.isnan(angle_error_deg):
            continue
        timestamps.append(timestamp)
        ray_distances.append(ray_distance)
        angle_errors.append(angle_error_deg)

    return {
        "times": np.asarray(timestamps, dtype=float),
        "ray_distances": np.asarray(ray_distances, dtype=float),
        "angle_errors_deg": np.asarray(angle_errors, dtype=float),
    }


def build_stats(
    scenario_name: str,
    target_name: str,
    tag_id: str,
    sensor_times: np.ndarray,
    sensor_positions: np.ndarray,
    reference_positions: np.ndarray,
    valid_mask: np.ndarray,
    reason: str | None = None,
) -> dict:
    stats = {
        "scenario": scenario_name,
        "target": target_name,
        "tag_id": tag_id,
        "matched_samples": int(np.sum(valid_mask)) if valid_mask.size else 0,
        "fused_samples_total": int(sensor_times.size),
        "mean_error_3d_m": None,
        "median_error_3d_m": None,
        "p95_error_3d_m": None,
        "max_error_3d_m": None,
        "rmse_3d_m": None,
        "mean_error_xy_m": None,
        "median_error_xy_m": None,
        "mean_abs_error_z_m": None,
        "median_abs_error_z_m": None,
    }
    if reason:
        stats["status"] = "no_data"
        stats["reason"] = reason
        return stats

    aligned_sensor = sensor_positions[valid_mask]
    aligned_reference = reference_positions[valid_mask]
    errors = aligned_sensor - aligned_reference
    err_3d = np.linalg.norm(errors, axis=1)
    err_xy = np.linalg.norm(errors[:, :2], axis=1)
    err_z_abs = np.abs(errors[:, 2])

    stats.update(
        {
            "status": "ok",
            "mean_error_3d_m": float(np.mean(err_3d)),
            "median_error_3d_m": float(np.median(err_3d)),
            "p95_error_3d_m": float(np.percentile(err_3d, 95)),
            "max_error_3d_m": float(np.max(err_3d)),
            "rmse_3d_m": float(np.sqrt(np.mean(err_3d ** 2))),
            "mean_error_xy_m": float(np.mean(err_xy)),
            "median_error_xy_m": float(np.median(err_xy)),
            "mean_abs_error_z_m": float(np.mean(err_z_abs)),
            "median_abs_error_z_m": float(np.median(err_z_abs)),
        }
    )
    return stats


def build_relative_time(sensor_times: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
    if sensor_times.size == 0 or not np.any(valid_mask):
        return np.asarray([], dtype=float)
    valid_times = sensor_times[valid_mask]
    return valid_times - valid_times[0]


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def get_position_eval_dir(scenario_dir: Path) -> Path:
    path = scenario_dir / "position_eval"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_ble_eval_dir(scenario_dir: Path) -> Path:
    path = scenario_dir / "ble_only_eval"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_summary_root(scenario_root: Path) -> Path:
    path = scenario_root / "_summary"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_position_summary_tables_dir(scenario_root: Path) -> Path:
    path = get_summary_root(scenario_root) / "position" / "tables"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_position_summary_boxplots_dir(scenario_root: Path) -> Path:
    path = get_summary_root(scenario_root) / "position" / "boxplots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_ble_summary_tables_dir(scenario_root: Path) -> Path:
    path = get_summary_root(scenario_root) / "ble_only" / "tables"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_ble_summary_boxplots_dir(scenario_root: Path) -> Path:
    path = get_summary_root(scenario_root) / "ble_only" / "boxplots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_summary_readme(summary_root: Path) -> None:
    content = """Souhrn scenario evaluace

Tato slozka obsahuje post-processed vystupy offline pipeline pro porovnani
scenaru senzoru proti OptiTracku.

Struktura:
- evaluation_summary.json
  Strojove citelny souhrn celeho behu.
- position/
  Evaluace scenaru, ktere produkuji prostorovou pozici:
  radar1, radar2, 2x_radar, 2x_ble, radar1_2x_ble, radar2_2x_ble, fusion
- position/tables/
  Per-target serazene tabulky s 3D metrikami.
- position/boxplots/
  Per-target boxploty rozdeleni 3D chyby.
- ble_only/
  Evaluace single-BLE scenaru: ble1, ble2
- ble_only/tables/
  Per-target serazene tabulky BLE-only metrik.
- ble_only/boxplots/
  Per-target boxploty ray distance a angle error.

Per-scenario slozky:
- <scenario>/position_eval/
  Per-target stats JSON + 2D mapa + timeline 3D chyby + XYZ timeline.
- <scenario>/ble_only_eval/
  Per-target stats JSON + ray-distance timeline + angle-error timeline.

Rozdeleni metrik:
- position metriky porovnavaji odhadnutou 3D pozici proti OptiTracku
- BLE-only metriky neporovnavaji plnou 3D pozici, ale:
  - ray distance: kolma vzdalenost GT bodu od BLE paprsku
  - angle error: uhlova chyba mezi BLE paprskem a smerem na GT

Doporucene poradi otevreni:
1. _summary/position/tables/summary_table_Phantom4.jpg
2. _summary/position/tables/summary_table_Vysavac3.jpg
3. _summary/position/boxplots/
4. _summary/ble_only/tables/
5. detailni slozky jednotlivych scenaru
"""
    (summary_root / "README.txt").write_text(content, encoding="utf-8")


def build_error_vectors(
    sensor_positions: np.ndarray,
    reference_positions: np.ndarray,
    valid_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if sensor_positions.size == 0 or not np.any(valid_mask):
        return (
            np.empty((0, 3), dtype=float),
            np.asarray([], dtype=float),
            np.asarray([], dtype=float),
        )
    aligned_errors = sensor_positions[valid_mask] - reference_positions[valid_mask]
    err_3d = np.linalg.norm(aligned_errors, axis=1)
    err_xy = np.linalg.norm(aligned_errors[:, :2], axis=1)
    return aligned_errors, err_3d, err_xy


def save_2d_map(
    output_path: Path,
    scenario_name: str,
    target_name: str,
    sensor_positions: np.ndarray,
    reference_positions: np.ndarray,
    valid_mask: np.ndarray,
) -> None:
    ensure_parent_dir(output_path)
    fig, ax = plt.subplots(figsize=(8, 8))
    if np.any(valid_mask):
        aligned_reference = reference_positions[valid_mask]
        aligned_sensor = sensor_positions[valid_mask]
        ax.plot(aligned_reference[:, 0], aligned_reference[:, 1], label="OptiTrack", color=COLOR_OPTITRACK, linewidth=2.0)
        ax.plot(aligned_sensor[:, 0], aligned_sensor[:, 1], label="Fusion", color=COLOR_FUSION, linewidth=1.25, alpha=0.9)
        ax.scatter(aligned_sensor[:, 0], aligned_sensor[:, 1], s=10, color=COLOR_FUSION, alpha=0.28)
        ax.legend(loc="best")
    else:
        ax.text(0.5, 0.5, "No overlapping samples", ha="center", va="center", color=COLOR_NO_DATA, transform=ax.transAxes)
    ax.set_title(f"{scenario_name} | {target_name} | 2D map")
    ax.set_xlabel("X [m]")
    ax.set_ylabel("Y [m]")
    ax.grid(True, color=COLOR_GRID, alpha=0.7, linewidth=0.8)
    ax.tick_params(colors=COLOR_TEXT)
    ax.axis("equal")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_error_timeline(
    output_path: Path,
    scenario_name: str,
    target_name: str,
    sensor_times: np.ndarray,
    sensor_positions: np.ndarray,
    reference_positions: np.ndarray,
    valid_mask: np.ndarray,
    stats: dict,
) -> None:
    ensure_parent_dir(output_path)
    fig, ax = plt.subplots(figsize=(10, 4))
    if np.any(valid_mask):
        _, err_3d, _ = build_error_vectors(sensor_positions, reference_positions, valid_mask)
        t_rel = build_relative_time(sensor_times, valid_mask)
        ax.plot(t_rel, err_3d, color=COLOR_ERROR, linewidth=1.35)
        ax.axhline(stats["mean_error_3d_m"], color=COLOR_TEXT, linestyle="--", linewidth=1.0, label="Mean 3D error")
        ax.legend(loc="best")
    else:
        ax.text(0.5, 0.5, "No overlapping samples", ha="center", va="center", color=COLOR_NO_DATA, transform=ax.transAxes)
    ax.set_title(f"{scenario_name} | {target_name} | 3D error timeline")
    ax.set_xlabel("Time from first matched sample [s]")
    ax.set_ylabel("3D error [m]")
    ax.grid(True, color=COLOR_GRID, alpha=0.7, linewidth=0.8)
    ax.tick_params(colors=COLOR_TEXT)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_simple_timeline(
    output_path: Path,
    title: str,
    ylabel: str,
    timestamps: np.ndarray,
    values: np.ndarray,
    color: str,
) -> None:
    ensure_parent_dir(output_path)
    fig, ax = plt.subplots(figsize=(10, 4))
    if timestamps.size > 0 and values.size > 0:
        t_rel = timestamps - timestamps[0]
        ax.plot(t_rel, values, color=color, linewidth=1.3)
    else:
        ax.text(0.5, 0.5, "No overlapping samples", ha="center", va="center", color=COLOR_NO_DATA, transform=ax.transAxes)
    ax.set_title(title)
    ax.set_xlabel("Time from first matched sample [s]")
    ax.set_ylabel(ylabel)
    ax.grid(True, color=COLOR_GRID, alpha=0.7, linewidth=0.8)
    ax.tick_params(colors=COLOR_TEXT)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_axes_timeline(
    output_path: Path,
    scenario_name: str,
    target_name: str,
    sensor_times: np.ndarray,
    sensor_positions: np.ndarray,
    reference_positions: np.ndarray,
    valid_mask: np.ndarray,
) -> None:
    ensure_parent_dir(output_path)
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    axis_labels = ("X", "Y", "Z")

    if np.any(valid_mask):
        aligned_sensor = sensor_positions[valid_mask]
        aligned_reference = reference_positions[valid_mask]
        t_rel = build_relative_time(sensor_times, valid_mask)
        for axis_index, axis_name in enumerate(axis_labels):
            axes[axis_index].plot(t_rel, aligned_reference[:, axis_index], label="OptiTrack", color=COLOR_OPTITRACK, linewidth=2.0)
            axes[axis_index].plot(t_rel, aligned_sensor[:, axis_index], label="Fusion", color=COLOR_FUSION, linewidth=1.15)
            axes[axis_index].set_ylabel(f"{axis_name} [m]")
            axes[axis_index].grid(True, color=COLOR_GRID, alpha=0.7, linewidth=0.8)
            axes[axis_index].tick_params(colors=COLOR_TEXT)
        axes[0].legend(loc="best")
    else:
        for axis_index, axis_name in enumerate(axis_labels):
            axes[axis_index].text(0.5, 0.5, "No overlapping samples", ha="center", va="center", color=COLOR_NO_DATA, transform=axes[axis_index].transAxes)
            axes[axis_index].set_ylabel(f"{axis_name} [m]")
            axes[axis_index].grid(True, color=COLOR_GRID, alpha=0.7, linewidth=0.8)
            axes[axis_index].tick_params(colors=COLOR_TEXT)

    axes[-1].set_xlabel("Time from first matched sample [s]")
    fig.suptitle(f"{scenario_name} | {target_name} | axes timeline")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_boxplot(
    output_path: Path,
    target_name: str,
    scenario_order: list[str],
    error_series_by_scenario: dict[str, np.ndarray],
    label_map: dict[str, str] | None = None,
) -> None:
    ensure_parent_dir(output_path)
    labels = []
    values = []
    for scenario_name in scenario_order:
        errors = error_series_by_scenario.get(scenario_name)
        if errors is None or errors.size == 0:
            continue
        labels.append(label_map.get(scenario_name, scenario_name) if label_map else scenario_name)
        values.append(errors)

    fig, ax = plt.subplots(figsize=(max(10, len(labels) * 1.2), 5.5))
    if values:
        box = ax.boxplot(
            values,
            tick_labels=labels,
            patch_artist=True,
            showfliers=False,
            medianprops={"color": COLOR_ERROR, "linewidth": 1.4},
            boxprops={"edgecolor": COLOR_FUSION, "linewidth": 1.2},
            whiskerprops={"color": COLOR_FUSION, "linewidth": 1.1},
            capprops={"color": COLOR_FUSION, "linewidth": 1.1},
        )
        for patch in box["boxes"]:
            patch.set_facecolor(COLOR_FUSION)
            patch.set_alpha(0.45)
    else:
        ax.text(0.5, 0.5, "No valid scenario data", ha="center", va="center", color=COLOR_NO_DATA, transform=ax.transAxes)

    ax.set_title(f"All scenarios | {target_name} | 3D error boxplot")
    ax.set_ylabel("3D error [m]")
    ax.grid(True, axis="y", color=COLOR_GRID, alpha=0.7, linewidth=0.8)
    ax.tick_params(axis="x", rotation=25, colors=COLOR_TEXT)
    ax.tick_params(axis="y", colors=COLOR_TEXT)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_named_boxplot(
    output_path: Path,
    title: str,
    ylabel: str,
    scenario_order: list[str],
    series_by_scenario: dict[str, np.ndarray],
    *,
    color: str,
    label_map: dict[str, str] | None = None,
) -> None:
    ensure_parent_dir(output_path)
    labels = []
    values = []
    for scenario_name in scenario_order:
        series = series_by_scenario.get(scenario_name)
        if series is None or series.size == 0:
            continue
        labels.append(label_map.get(scenario_name, scenario_name) if label_map else scenario_name)
        values.append(series)

    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 1.2), 5.5))
    if values:
        box = ax.boxplot(
            values,
            tick_labels=labels,
            patch_artist=True,
            showfliers=False,
            medianprops={"color": COLOR_ERROR, "linewidth": 1.4},
            boxprops={"edgecolor": color, "linewidth": 1.2},
            whiskerprops={"color": color, "linewidth": 1.1},
            capprops={"color": color, "linewidth": 1.1},
        )
        for patch in box["boxes"]:
            patch.set_facecolor(color)
            patch.set_alpha(0.45)
    else:
        ax.text(0.5, 0.5, "No valid scenario data", ha="center", va="center", color=COLOR_NO_DATA, transform=ax.transAxes)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(True, axis="y", color=COLOR_GRID, alpha=0.7, linewidth=0.8)
    ax.tick_params(axis="x", rotation=25, colors=COLOR_TEXT)
    ax.tick_params(axis="y", colors=COLOR_TEXT)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def save_summary_table_csv(output_path: Path, rows: list[dict]) -> None:
    ensure_parent_dir(output_path)
    fieldnames = [
        "rank",
        "scenario",
        "target",
        "status",
        "matched_samples",
        "fused_samples_total",
        "mean_error_3d_m",
        "median_error_3d_m",
        "p95_error_3d_m",
        "max_error_3d_m",
        "rmse_3d_m",
        "mean_error_xy_m",
        "median_error_xy_m",
        "mean_abs_error_z_m",
        "median_abs_error_z_m",
        "reason",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def save_ble_summary_table_csv(output_path: Path, rows: list[dict]) -> None:
    ensure_parent_dir(output_path)
    fieldnames = [
        "rank",
        "scenario",
        "target",
        "status",
        "matched_samples",
        "mean_ray_distance_m",
        "median_ray_distance_m",
        "p95_ray_distance_m",
        "max_ray_distance_m",
        "rmse_ray_distance_m",
        "mean_angle_error_deg",
        "median_angle_error_deg",
        "p95_angle_error_deg",
        "max_angle_error_deg",
        "reason",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def format_table_value(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def save_summary_table_image(output_path: Path, rows: list[dict]) -> None:
    ensure_parent_dir(output_path)
    columns = [
        ("rank", "Rank"),
        ("scenario", "Scenario"),
        ("status", "Status"),
        ("matched_samples", "Matched"),
        ("rmse_3d_m", "RMSE 3D"),
        ("mean_error_3d_m", "Mean 3D"),
        ("p95_error_3d_m", "P95 3D"),
        ("mean_error_xy_m", "Mean XY"),
        ("mean_abs_error_z_m", "Mean |Z|"),
    ]
    table_data = [[format_table_value(row.get(key)) for key, _ in columns] for row in rows]
    headers = [label for _, label in columns]

    row_count = max(1, len(table_data))
    fig_height = max(4.5, 1.0 + (row_count * 0.35))
    fig, ax = plt.subplots(figsize=(13, fig_height))
    ax.axis("off")
    table = ax.table(
        cellText=table_data,
        colLabels=headers,
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.3)

    for (row_index, col_index), cell in table.get_celld().items():
        cell.set_edgecolor(COLOR_GRID)
        cell.set_linewidth(0.8)
        if row_index == 0:
            cell.set_facecolor(COLOR_OPTITRACK)
            cell.set_text_props(color="white", weight="bold")
        else:
            cell.set_facecolor("#F8FAFC" if row_index % 2 else "#EEF2F7")
            if col_index == 2 and row_index - 1 < len(rows):
                status = rows[row_index - 1].get("status")
                if status != "ok":
                    cell.set_text_props(color=COLOR_ERROR, weight="bold")

    target_name = rows[0].get("target", "Unknown target") if rows else "Unknown target"
    ax.set_title(f"Scenario evaluation summary | {target_name}", color=COLOR_TEXT, pad=12)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def save_ble_summary_table_image(output_path: Path, rows: list[dict]) -> None:
    ensure_parent_dir(output_path)
    columns = [
        ("rank", "Rank"),
        ("scenario", "Scenario"),
        ("status", "Status"),
        ("matched_samples", "Matched"),
        ("rmse_ray_distance_m", "RMSE ray"),
        ("mean_ray_distance_m", "Mean ray"),
        ("p95_ray_distance_m", "P95 ray"),
        ("mean_angle_error_deg", "Mean angle"),
        ("p95_angle_error_deg", "P95 angle"),
    ]
    table_data = [[format_table_value(row.get(key)) for key, _ in columns] for row in rows]
    headers = [label for _, label in columns]

    row_count = max(1, len(table_data))
    fig_height = max(4.0, 1.0 + (row_count * 0.35))
    fig, ax = plt.subplots(figsize=(13, fig_height))
    ax.axis("off")
    table = ax.table(cellText=table_data, colLabels=headers, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.3)

    for (row_index, col_index), cell in table.get_celld().items():
        cell.set_edgecolor(COLOR_GRID)
        cell.set_linewidth(0.8)
        if row_index == 0:
            cell.set_facecolor(COLOR_FUSION)
            cell.set_text_props(color="white", weight="bold")
        else:
            cell.set_facecolor("#F8FAFC" if row_index % 2 else "#EEF2F7")
            if col_index == 2 and row_index - 1 < len(rows):
                status = rows[row_index - 1].get("status")
                if status != "ok":
                    cell.set_text_props(color=COLOR_ERROR, weight="bold")

    target_name = rows[0].get("target", "Unknown target") if rows else "Unknown target"
    ax.set_title(f"BLE-only evaluation summary | {target_name}", color=COLOR_TEXT, pad=12)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def rank_summary_rows(rows: list[dict], scenario_order: list[str]) -> list[dict]:
    scenario_position = {scenario_name: index for index, scenario_name in enumerate(scenario_order)}

    ok_rows = [dict(row) for row in rows if row.get("status") == "ok" and row.get("rmse_3d_m") is not None]
    no_data_rows = [dict(row) for row in rows if row.get("status") != "ok" or row.get("rmse_3d_m") is None]

    ok_rows.sort(key=lambda row: (float(row["rmse_3d_m"]), scenario_position.get(row["scenario"], 9999)))
    no_data_rows.sort(key=lambda row: scenario_position.get(row["scenario"], 9999))

    ranked_rows = []
    for rank, row in enumerate(ok_rows, start=1):
        row["rank"] = rank
        ranked_rows.append(row)
    for row in no_data_rows:
        row["rank"] = None
        ranked_rows.append(row)

    return ranked_rows


def rank_ble_summary_rows(rows: list[dict], scenario_order: list[str]) -> list[dict]:
    scenario_position = {scenario_name: index for index, scenario_name in enumerate(scenario_order)}

    ok_rows = [dict(row) for row in rows if row.get("status") == "ok" and row.get("rmse_ray_distance_m") is not None]
    no_data_rows = [dict(row) for row in rows if row.get("status") != "ok" or row.get("rmse_ray_distance_m") is None]

    ok_rows.sort(key=lambda row: (float(row["rmse_ray_distance_m"]), scenario_position.get(row["scenario"], 9999)))
    no_data_rows.sort(key=lambda row: scenario_position.get(row["scenario"], 9999))

    ranked_rows = []
    for rank, row in enumerate(ok_rows, start=1):
        row["rank"] = rank
        ranked_rows.append(row)
    for row in no_data_rows:
        row["rank"] = None
        ranked_rows.append(row)
    return ranked_rows


def build_rank_label_map(rows: list[dict]) -> dict[str, str]:
    label_map = {}
    for row in rows:
        scenario_name = row.get("scenario")
        rank = row.get("rank")
        if not scenario_name:
            continue
        if rank is None:
            label_map[scenario_name] = str(scenario_name)
        else:
            label_map[scenario_name] = f"{rank}. {scenario_name}"
    return label_map


def evaluate_target_in_scenario(
    scenario_name: str,
    scenario_dir: Path,
    target_name: str,
    target_config: dict,
    reference_track: dict[str, np.ndarray],
) -> dict:
    fused_path = scenario_dir / "fused.ndjson"
    output_dir = get_position_eval_dir(scenario_dir)
    sensor_times, sensor_positions = load_fused_track(fused_path, target_config["tag_id"])

    if sensor_times.size == 0:
        reference_positions = np.empty((0, 3), dtype=float)
        valid_mask = np.asarray([], dtype=bool)
        stats = build_stats(
            scenario_name,
            target_name,
            target_config["tag_id"],
            sensor_times,
            sensor_positions,
            reference_positions,
            valid_mask,
            reason="V tomto scenari nebyly nalezeny zadne fused pozice pro dany tag.",
        )
    else:
        reference_positions, valid_mask = interpolate_reference(sensor_times, reference_track)
        if not np.any(valid_mask):
            stats = build_stats(
                scenario_name,
                target_name,
                target_config["tag_id"],
                sensor_times,
                sensor_positions,
                reference_positions,
                valid_mask,
                reason="Neexistuje casovy prekryv fused dat s OptiTrack referenci.",
            )
        else:
            stats = build_stats(
                scenario_name,
                target_name,
                target_config["tag_id"],
                sensor_times,
                sensor_positions,
                reference_positions,
                valid_mask,
            )

    _, err_3d, _ = build_error_vectors(sensor_positions, reference_positions, valid_mask)

    write_json(output_dir / f"stats_{target_name}.json", stats)
    save_2d_map(
        output_dir / f"{scenario_name}_{target_name}_2D_map.jpg",
        scenario_name,
        target_name,
        sensor_positions,
        reference_positions,
        valid_mask,
    )
    save_error_timeline(
        output_dir / f"{scenario_name}_{target_name}_error_timeline.jpg",
        scenario_name,
        target_name,
        sensor_times,
        sensor_positions,
        reference_positions,
        valid_mask,
        stats,
    )
    save_axes_timeline(
        output_dir / f"{scenario_name}_{target_name}_axes_timeline.jpg",
        scenario_name,
        target_name,
        sensor_times,
        sensor_positions,
        reference_positions,
        valid_mask,
    )
    return {
        "stats": stats,
        "error_3d": err_3d,
    }


def evaluate_ble_only_target_in_scenario(
    scenario_name: str,
    scenario_dir: Path,
    target_name: str,
    target_config: dict,
    reference_track: dict[str, np.ndarray],
    raw_field_name: str,
) -> dict:
    fused_path = scenario_dir / "fused.ndjson"
    output_dir = get_ble_eval_dir(scenario_dir)
    metrics = load_ble_only_metrics(fused_path, raw_field_name, reference_track, target_config["tag_id"])
    ray_distances = metrics["ray_distances"]
    angle_errors = metrics["angle_errors_deg"]
    times = metrics["times"]

    stats = {
        "scenario": scenario_name,
        "target": target_name,
        "tag_id": target_config["tag_id"],
        "matched_samples": int(ray_distances.size),
        "mean_ray_distance_m": None,
        "median_ray_distance_m": None,
        "p95_ray_distance_m": None,
        "max_ray_distance_m": None,
        "rmse_ray_distance_m": None,
        "mean_angle_error_deg": None,
        "median_angle_error_deg": None,
        "p95_angle_error_deg": None,
        "max_angle_error_deg": None,
    }

    if ray_distances.size == 0:
        stats["status"] = "no_data"
        stats["reason"] = "V tomto BLE-only scenari nebyl nalezen casovy prekryv paprsku a GT."
    else:
        stats.update(
            {
                "status": "ok",
                "mean_ray_distance_m": float(np.mean(ray_distances)),
                "median_ray_distance_m": float(np.median(ray_distances)),
                "p95_ray_distance_m": float(np.percentile(ray_distances, 95)),
                "max_ray_distance_m": float(np.max(ray_distances)),
                "rmse_ray_distance_m": float(np.sqrt(np.mean(ray_distances ** 2))),
                "mean_angle_error_deg": float(np.mean(angle_errors)),
                "median_angle_error_deg": float(np.median(angle_errors)),
                "p95_angle_error_deg": float(np.percentile(angle_errors, 95)),
                "max_angle_error_deg": float(np.max(angle_errors)),
            }
        )

    write_json(output_dir / f"stats_ble_only_{target_name}.json", stats)
    save_simple_timeline(
        output_dir / f"{scenario_name}_{target_name}_ray_distance_timeline.jpg",
        f"{scenario_name} | {target_name} | ray distance timeline",
        "Ray distance [m]",
        times,
        ray_distances,
        COLOR_ERROR,
    )
    save_simple_timeline(
        output_dir / f"{scenario_name}_{target_name}_angle_error_timeline.jpg",
        f"{scenario_name} | {target_name} | angle error timeline",
        "Angle error [deg]",
        times,
        angle_errors,
        COLOR_OPTITRACK,
    )
    return {
        "stats": stats,
        "ray_distances": ray_distances,
        "angle_errors_deg": angle_errors,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir = resolve_run_dir(args.run_dir)
    scenario_root = resolve_scenario_root(args.scenario_root, run_dir=run_dir)
    optitrack_csv = Path(args.optitrack_csv).resolve()

    if not scenario_root.exists():
        raise FileNotFoundError(f"Scenario root neexistuje: {scenario_root}")
    if not optitrack_csv.exists():
        raise FileNotFoundError(f"OptiTrack CSV nebyl nalezen: {optitrack_csv}")

    requested = list(dict.fromkeys(args.scenarios))
    unknown = [name for name in requested if name not in SCENARIO_TOPICS]
    if unknown:
        raise ValueError(f"Neznamy scenar: {', '.join(unknown)}")

    reference = load_optitrack_reference(optitrack_csv)
    summary_root = get_summary_root(scenario_root)
    write_summary_readme(summary_root)
    position_tables_dir = get_position_summary_tables_dir(scenario_root)
    position_boxplots_dir = get_position_summary_boxplots_dir(scenario_root)
    ble_tables_dir = get_ble_summary_tables_dir(scenario_root)
    ble_boxplots_dir = get_ble_summary_boxplots_dir(scenario_root)
    boxplot_data = {target_name: {} for target_name in TARGETS}
    ble_boxplot_ray_data = {target_name: {} for target_name in TARGETS}
    ble_boxplot_angle_data = {target_name: {} for target_name in TARGETS}
    position_summary_rows = []
    ble_summary_rows = []
    evaluation_summary = {
        "scenario_root": str(scenario_root),
        "optitrack_csv": str(optitrack_csv),
        "delay_sec": DELAY_SEC,
        "offset_x": OFFSET_X,
        "offset_y": OFFSET_Y,
        "offset_z": OFFSET_Z,
        "axis_mapping": {
            "sensor_x": "optitrack_z + OFFSET_X",
            "sensor_y": "optitrack_x + OFFSET_Y",
            "sensor_z": "optitrack_y + OFFSET_Z",
        },
        "position_scenarios": {},
        "ble_only_scenarios": {},
        "scenarios": {},
    }

    for scenario_name in requested:
        scenario_dir = scenario_root / scenario_name
        fused_path = scenario_dir / "fused.ndjson"
        if not fused_path.exists():
            raise FileNotFoundError(f"Ve scenari {scenario_name} chybi {fused_path}")

        print(f"Vyhodnocuji scenar {scenario_name} ...")
        scenario_results = {}
        if scenario_name in BLE_ONLY_SCENARIOS:
            raw_field_name = BLE_ONLY_SCENARIOS[scenario_name]
            for target_name, target_config in TARGETS.items():
                evaluation_result = evaluate_ble_only_target_in_scenario(
                    scenario_name,
                    scenario_dir,
                    target_name,
                    target_config,
                    reference[target_name],
                    raw_field_name,
                )
                stats = evaluation_result["stats"]
                scenario_results[target_name] = stats
                ble_boxplot_ray_data[target_name][scenario_name] = evaluation_result["ray_distances"]
                ble_boxplot_angle_data[target_name][scenario_name] = evaluation_result["angle_errors_deg"]
                summary_row = dict(stats)
                summary_row["reason"] = stats.get("reason")
                ble_summary_rows.append(summary_row)
                if stats["status"] == "ok":
                    print(
                        f"- {target_name}: RMSE ray = {stats['rmse_ray_distance_m']:.3f} m "
                        f"({stats['matched_samples']} vzorku)"
                    )
                else:
                    print(f"- {target_name}: bez platneho BLE-only prekryvu ({stats['reason']})")
            evaluation_summary["ble_only_scenarios"][scenario_name] = scenario_results
        elif scenario_name in RADAR_ONLY_SCENARIOS:
            output_dir = get_position_eval_dir(scenario_dir)
            radar_tracks = load_radar_tracks_by_matching(
                fused_path,
                reference,
                list(TARGETS.keys()),
            )
            for target_name, target_config in TARGETS.items():
                sensor_times, sensor_positions = radar_tracks[target_name]
                if sensor_times.size == 0:
                    reference_positions = np.empty((0, 3), dtype=float)
                    valid_mask = np.asarray([], dtype=bool)
                    stats = build_stats(
                        scenario_name,
                        target_name,
                        target_config["tag_id"],
                        sensor_times,
                        sensor_positions,
                        reference_positions,
                        valid_mask,
                        reason="Radar-only matching nenasel zadne validni anonymni tracky pro dany cil.",
                    )
                    err_3d = np.asarray([], dtype=float)
                else:
                    reference_positions, valid_mask = interpolate_reference(sensor_times, reference[target_name])
                    if not np.any(valid_mask):
                        stats = build_stats(
                            scenario_name,
                            target_name,
                            target_config["tag_id"],
                            sensor_times,
                            sensor_positions,
                            reference_positions,
                            valid_mask,
                            reason="Radar-only matching nema casovy prekryv s OptiTrack referenci.",
                        )
                        err_3d = np.asarray([], dtype=float)
                    else:
                        stats = build_stats(
                            scenario_name,
                            target_name,
                            target_config["tag_id"],
                            sensor_times,
                            sensor_positions,
                            reference_positions,
                            valid_mask,
                        )
                        _, err_3d, _ = build_error_vectors(sensor_positions, reference_positions, valid_mask)

                save_2d_map(
                    output_dir / f"{scenario_name}_{target_name}_2D_map.jpg",
                    scenario_name,
                    target_name,
                    sensor_positions,
                    reference_positions,
                    valid_mask,
                )
                save_error_timeline(
                    output_dir / f"{scenario_name}_{target_name}_error_timeline.jpg",
                    scenario_name,
                    target_name,
                    sensor_times,
                    sensor_positions,
                    reference_positions,
                    valid_mask,
                    stats,
                )
                save_axes_timeline(
                    output_dir / f"{scenario_name}_{target_name}_axes_timeline.jpg",
                    scenario_name,
                    target_name,
                    sensor_times,
                    sensor_positions,
                    reference_positions,
                    valid_mask,
                )

                write_json(output_dir / f"stats_{target_name}.json", stats)
                scenario_results[target_name] = stats
                boxplot_data[target_name][scenario_name] = err_3d
                summary_row = dict(stats)
                summary_row["reason"] = stats.get("reason")
                position_summary_rows.append(summary_row)
                if stats["status"] == "ok":
                    print(f"- {target_name}: RMSE 3D = {stats['rmse_3d_m']:.3f} m ({stats['matched_samples']} vzorku)")
                else:
                    print(f"- {target_name}: bez platneho radar-only matchingu ({stats['reason']})")
            evaluation_summary["position_scenarios"][scenario_name] = scenario_results
        else:
            for target_name, target_config in TARGETS.items():
                evaluation_result = evaluate_target_in_scenario(
                    scenario_name,
                    scenario_dir,
                    target_name,
                    target_config,
                    reference[target_name],
                )
                stats = evaluation_result["stats"]
                scenario_results[target_name] = stats
                boxplot_data[target_name][scenario_name] = evaluation_result["error_3d"]
                summary_row = dict(stats)
                summary_row["reason"] = stats.get("reason")
                position_summary_rows.append(summary_row)
                if stats["status"] == "ok":
                    print(f"- {target_name}: RMSE 3D = {stats['rmse_3d_m']:.3f} m ({stats['matched_samples']} vzorku)")
                else:
                    print(f"- {target_name}: bez platneho prekryvu ({stats['reason']})")
            evaluation_summary["position_scenarios"][scenario_name] = scenario_results

        evaluation_summary["scenarios"][scenario_name] = scenario_results

    write_json(summary_root / "evaluation_summary.json", evaluation_summary)

    rows_by_target = {target_name: [] for target_name in TARGETS}
    for row in position_summary_rows:
        rows_by_target[row["target"]].append(row)

    ranked_tables = {}
    rank_label_maps = {}
    for target_name, rows in rows_by_target.items():
        ranked_rows = rank_summary_rows(rows, requested)
        ranked_tables[target_name] = ranked_rows
        rank_label_maps[target_name] = build_rank_label_map(ranked_rows)
        write_json(position_tables_dir / f"summary_table_{target_name}.json", {"rows": ranked_rows})
        save_summary_table_csv(position_tables_dir / f"summary_table_{target_name}.csv", ranked_rows)
        save_summary_table_image(position_tables_dir / f"summary_table_{target_name}.jpg", ranked_rows)

    write_json(position_tables_dir / "summary_table.json", ranked_tables)

    ble_rows_by_target = {target_name: [] for target_name in TARGETS}
    for row in ble_summary_rows:
        ble_rows_by_target[row["target"]].append(row)

    ble_ranked_tables = {}
    ble_rank_label_maps = {}
    for target_name, rows in ble_rows_by_target.items():
        ranked_rows = rank_ble_summary_rows(rows, list(BLE_ONLY_SCENARIOS.keys()))
        ble_ranked_tables[target_name] = ranked_rows
        ble_rank_label_maps[target_name] = build_rank_label_map(ranked_rows)
        write_json(ble_tables_dir / f"summary_table_ble_only_{target_name}.json", {"rows": ranked_rows})
        save_ble_summary_table_csv(ble_tables_dir / f"summary_table_ble_only_{target_name}.csv", ranked_rows)
        save_ble_summary_table_image(ble_tables_dir / f"summary_table_ble_only_{target_name}.jpg", ranked_rows)

    write_json(ble_tables_dir / "summary_table_ble_only.json", ble_ranked_tables)
    for target_name in TARGETS:
        save_boxplot(
            position_boxplots_dir / f"boxplot_all_scenarios_{target_name}.jpg",
            target_name,
            [name for name in requested if name not in BLE_ONLY_SCENARIOS],
            boxplot_data[target_name],
            rank_label_maps.get(target_name),
        )
        save_named_boxplot(
            ble_boxplots_dir / f"boxplot_ble_ray_distance_{target_name}.jpg",
            f"BLE-only scenarios | {target_name} | ray distance boxplot",
            "Ray distance [m]",
            [name for name in requested if name in BLE_ONLY_SCENARIOS],
            ble_boxplot_ray_data[target_name],
            color=COLOR_FUSION,
            label_map=ble_rank_label_maps.get(target_name),
        )
        save_named_boxplot(
            ble_boxplots_dir / f"boxplot_ble_angle_error_{target_name}.jpg",
            f"BLE-only scenarios | {target_name} | angle error boxplot",
            "Angle error [deg]",
            [name for name in requested if name in BLE_ONLY_SCENARIOS],
            ble_boxplot_angle_data[target_name],
            color=COLOR_OPTITRACK,
            label_map=ble_rank_label_maps.get(target_name),
        )
    print(f"Evaluace hotova: {summary_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
