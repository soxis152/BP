"""Vyhodnoceni fused vystupu proti OptiTrack ground truth."""

from __future__ import annotations

import argparse
from bisect import bisect_left
import json
import math
from pathlib import Path
import re
from statistics import mean, median

try:
    from Four.test_soubory.optitrack_xlsx import load_optitrack_take
except ImportError:
    try:
        from test_soubory.optitrack_xlsx import load_optitrack_take
    except ImportError:
        from ..test_soubory.optitrack_xlsx import load_optitrack_take


OFFSET_SEARCH_IDENTITY_MARGIN_METERS = 0.20


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Porovna fused vystup s OptiTrack ground truth.")
    parser.add_argument("--input-dir", required=True, help="Adresar experimentu s fused.ndjson.")
    parser.add_argument("--xlsx", required=True, help="OptiTrack XLSX export.")
    parser.add_argument("--sheet", default=None, help="Nazev sheetu. Vychozi je prvni.")
    parser.add_argument("--axis-x", default="x", help="Mapovani OptiTrack osy na systemovou X.")
    parser.add_argument("--axis-y", default="-z", help="Mapovani OptiTrack osy na systemovou Y.")
    parser.add_argument("--axis-z", default="y", help="Mapovani OptiTrack osy na systemovou Z.")
    parser.add_argument("--offset-x", type=float, default=0.0, help="Posun X po prevodu os.")
    parser.add_argument("--offset-y", type=float, default=0.0, help="Posun Y po prevodu os.")
    parser.add_argument("--offset-z", type=float, default=0.0, help="Posun Z po prevodu os.")
    parser.add_argument("--tag-map", action="append", default=[], help="Mapovani TAG_ID=RigidBodyName.")
    parser.add_argument("--time-offset", type=float, default=None, help="Manualni posun fused casu proti OptiTracku.")
    parser.add_argument("--search-offset-start", type=float, default=-5.0, help="Start hledani casoveho posunu.")
    parser.add_argument("--search-offset-end", type=float, default=5.0, help="Konec hledani casoveho posunu.")
    parser.add_argument("--search-offset-step", type=float, default=0.05, help="Krok hledani casoveho posunu.")
    parser.add_argument("--search-samples", type=int, default=2000, help="Max pocet vzorku pro automaticke hledani offsetu.")
    parser.add_argument("--output", default=None, help="Kam ulozit evaluation JSON. Vychozi je evaluation.json v input-dir.")
    return parser.parse_args()


def sanitize_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")


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
                }
            )
    if not records:
        raise ValueError(f"Soubor {fused_path} neobsahuje zadne fused zpravy.")
    return records


def infer_tag_mapping(records, body_names, explicit_mapping):
    mapping = dict(explicit_mapping)
    body_by_upper = {name.upper(): name for name in body_names}
    body_by_sanitized = {sanitize_name(name): name for name in body_names}

    for record in records:
        for obj in record["objects"]:
            tag_id = str(obj.get("tag_id", "")).strip()
            if not tag_id or tag_id in mapping:
                continue

            upper = tag_id.upper()
            if upper in body_by_upper:
                mapping[tag_id] = body_by_upper[upper]
            elif upper in body_by_sanitized:
                mapping[tag_id] = body_by_sanitized[upper]
    return mapping


def build_samples(records, tag_mapping):
    first_timestamp = records[0]["snapshot_timestamp"]
    total_snapshots = len(records)
    samples = []
    snapshots_by_tag = {tag_id: 0 for tag_id in tag_mapping}

    for record in records:
        relative_time = record["snapshot_timestamp"] - first_timestamp
        present_tags = set()
        for obj in record["objects"]:
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
                }
            )
        for tag_id in present_tags:
            snapshots_by_tag[tag_id] += 1

    return samples, total_snapshots, snapshots_by_tag


def build_ground_truth(take):
    trajectories = {}
    for body in take.rigid_bodies:
        points = []
        for frame in take.frames:
            if body.name in frame.bodies:
                x, y, z = frame.bodies[body.name]
                points.append((frame.time_seconds, x, y, z))
        trajectories[body.name] = points
    return trajectories


def interpolate_body_position(points, target_time):
    if not points:
        return None

    times = [point[0] for point in points]
    if target_time < times[0] or target_time > times[-1]:
        return None

    right_index = bisect_left(times, target_time)
    if right_index == 0:
        return points[0][1:]
    if right_index >= len(points):
        return points[-1][1:]

    left = points[right_index - 1]
    right = points[right_index]
    if math.isclose(right[0], left[0]):
        return left[1:]

    alpha = (target_time - left[0]) / (right[0] - left[0])
    return (
        left[1] + ((right[1] - left[1]) * alpha),
        left[2] + ((right[2] - left[2]) * alpha),
        left[3] + ((right[3] - left[3]) * alpha),
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


def evaluate_samples(samples, trajectories, time_offset, tag_mapping):
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

        error_item = {
            "tag_id": sample["tag_id"],
            "body_name": sample["body_name"],
            "gt_time": gt_time,
            "fused_time": sample["relative_time"],
            "confidence": sample["confidence"],
            "error_x_m": sample["x"] - assigned_position[0],
            "error_y_m": sample["y"] - assigned_position[1],
            "error_z_m": sample["z"] - assigned_position[2],
            "error_xy_m": distance_xy(fused_position, assigned_position),
            "error_3d_m": assigned_error,
        }
        errors.append(error_item)
        per_tag_errors[sample["tag_id"]].append(error_item)

        if best_other_error is not None and best_other_error + OFFSET_SEARCH_IDENTITY_MARGIN_METERS < assigned_error:
            identity_mismatch_counts[sample["tag_id"]] += 1

    return errors, per_tag_errors, identity_mismatch_counts


def estimate_time_offset(samples, trajectories, tag_mapping, start, end, step, max_samples):
    if not samples:
        return 0.0

    sample_step = max(1, len(samples) // max(1, max_samples))
    sampled = samples[::sample_step]

    best_offset = 0.0
    best_score = None
    current = start
    while current <= end + 1e-9:
        errors, _, _ = evaluate_samples(sampled, trajectories, current, tag_mapping)
        if errors:
            score = median(item["error_3d_m"] for item in errors)
            if best_score is None or score < best_score:
                best_score = score
                best_offset = current
        current += step

    return best_offset


def main() -> None:
    args = parse_args()
    run_dir = Path(args.input_dir).resolve()
    fused_path = run_dir / "fused.ndjson"
    records = load_fused_records(fused_path)

    take = load_optitrack_take(
        args.xlsx,
        sheet_name=args.sheet,
        axis_x=args.axis_x,
        axis_y=args.axis_y,
        axis_z=args.axis_z,
        offset_x=args.offset_x,
        offset_y=args.offset_y,
        offset_z=args.offset_z,
    )
    trajectories = build_ground_truth(take)
    explicit_mapping = parse_tag_map(args.tag_map)
    tag_mapping = infer_tag_mapping(records, [body.name for body in take.rigid_bodies], explicit_mapping)
    if not tag_mapping:
        raise ValueError(
            "Nepodarilo se odvodit mapovani fused tagu na rigid body. "
            "Pouzij --tag-map TAG_ID=RigidBodyName."
        )

    samples, total_snapshots, snapshots_by_tag = build_samples(records, tag_mapping)
    if not samples:
        raise ValueError("Ve fused datech nejsou zadne objekty odpovidajici mapovani tagu.")

    if args.time_offset is None:
        time_offset = estimate_time_offset(
            samples,
            trajectories,
            tag_mapping,
            args.search_offset_start,
            args.search_offset_end,
            args.search_offset_step,
            args.search_samples,
        )
        offset_source = "estimated"
    else:
        time_offset = args.time_offset
        offset_source = "manual"

    errors, per_tag_errors, identity_mismatch_counts = evaluate_samples(samples, trajectories, time_offset, tag_mapping)
    summary = summarize_errors(errors)

    per_tag_summary = {}
    for tag_id, tag_errors in per_tag_errors.items():
        tag_summary = summarize_errors(tag_errors)
        tag_summary["body_name"] = tag_mapping[tag_id]
        tag_summary["presence_ratio"] = (
            snapshots_by_tag.get(tag_id, 0) / total_snapshots if total_snapshots > 0 else 0.0
        )
        tag_summary["suspected_identity_mismatches"] = identity_mismatch_counts.get(tag_id, 0)
        per_tag_summary[tag_id] = tag_summary

    output = {
        "input_dir": str(run_dir),
        "xlsx": str(Path(args.xlsx).resolve()),
        "sheet": take.sheet_name,
        "axis_mapping": {"x": args.axis_x, "y": args.axis_y, "z": args.axis_z},
        "offset_m": {"x": args.offset_x, "y": args.offset_y, "z": args.offset_z},
        "time_offset_seconds": time_offset,
        "time_offset_source": offset_source,
        "fused_snapshots": total_snapshots,
        "mapped_tags": tag_mapping,
        "overall": summary,
        "per_tag": per_tag_summary,
    }

    output_path = Path(args.output).resolve() if args.output else (run_dir / "evaluation.json")
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Evaluation: ulozeno do {output_path}")
    print(f"Evaluation: time_offset={time_offset:.3f}s ({offset_source})")
    if summary.get("count", 0):
        print(
            "Evaluation: "
            f"count={summary['count']} "
            f"median_3d={summary['median_error_3d_m']:.3f}m "
            f"p95_3d={summary['p95_error_3d_m']:.3f}m "
            f"rmse_3d={summary['rmse_3d_m']:.3f}m"
        )
    else:
        print("Evaluation: nenasel jsem zadne porovnatelne vzorky.")


if __name__ == "__main__":
    main()
