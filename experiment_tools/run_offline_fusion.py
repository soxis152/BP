"""Offline prehrani scenaru pres jadro fusion.py bez MQTT brokeru."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import types
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = PROJECT_DIR.parent

for candidate in (PROJECT_ROOT, PROJECT_DIR, SCRIPT_DIR):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

try:
    from experiment_tools.scenario_pipeline_common import (
        SCENARIO_TOPICS,
        iter_ndjson_records,
        resolve_run_dir,
        resolve_scenario_root,
        write_json,
        write_ndjson_record,
    )
except ImportError:
    from scenario_pipeline_common import (
        SCENARIO_TOPICS,
        iter_ndjson_records,
        resolve_run_dir,
        resolve_scenario_root,
        write_json,
        write_ndjson_record,
    )


def ensure_stub_modules() -> None:
    if "db_handler" not in sys.modules and importlib.util.find_spec("asyncpg") is None:
        db_handler_stub = types.ModuleType("db_handler")

        class AsyncDBHandler:  # pragma: no cover - offline stub
            async def connect(self):
                raise RuntimeError("AsyncDBHandler stub should not be used in offline fusion.")

            async def init_tables(self):
                raise RuntimeError("AsyncDBHandler stub should not be used in offline fusion.")

            async def insert_batch(self, *_args, **_kwargs):
                raise RuntimeError("AsyncDBHandler stub should not be used in offline fusion.")

        db_handler_stub.AsyncDBHandler = AsyncDBHandler
        sys.modules["db_handler"] = db_handler_stub

    if "aiomqtt" not in sys.modules and importlib.util.find_spec("aiomqtt") is None:
        aiomqtt_stub = types.ModuleType("aiomqtt")

        class MqttError(Exception):
            pass

        class Client:  # pragma: no cover - offline stub
            def __init__(self, *_args, **_kwargs):
                raise RuntimeError("aiomqtt stub should not be used in offline fusion.")

        aiomqtt_stub.MqttError = MqttError
        aiomqtt_stub.Client = Client
        sys.modules["aiomqtt"] = aiomqtt_stub


def load_fusion_module():
    ensure_stub_modules()
    if "fusion" in sys.modules:
        return sys.modules["fusion"]

    fusion_path = PROJECT_DIR / "fusion.py"
    spec = importlib.util.spec_from_file_location("fusion", fusion_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Nepodarilo se nacist fusion modul z {fusion_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["fusion"] = module
    spec.loader.exec_module(module)
    return module


fusion = load_fusion_module()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vygeneruje fused.ndjson pro vsechny scenare offline.")
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
        "--scenarios",
        nargs="+",
        default=list(SCENARIO_TOPICS.keys()),
        help="Volitelny seznam scenaru, ktere se maji prepocitat.",
    )
    return parser.parse_args(argv)


def reset_fusion_state() -> None:
    fusion.shared_state["radar_points"].clear()
    fusion.shared_state["ble_tags"]["ble_1"].clear()
    fusion.shared_state["ble_tags"]["ble_2"].clear()
    fusion.shared_state["pair_memory"].clear()
    fusion.bad_message_count = 0


def ingest_raw_record(record: dict) -> None:
    topic = str(record.get("topic", "")).strip()
    payload_text = record.get("payload_text")
    if payload_text is None:
        raise ValueError(f"Raw record nema payload_text: {record}")
    data = json.loads(payload_text)
    source = fusion.validate_raw_message(topic, data)
    recorded_at = float(record.get("recorded_at") or record.get("payload_timestamp") or 0.0)

    if source == "radar":
        fusion.shared_state["radar_points"].append(data)
    else:
        normalized = dict(data)
        normalized["tag_id"] = fusion.normalize_ble_tag_id(normalized["tag_id"])
        normalized["_seen_at"] = recorded_at
        fusion.shared_state["ble_tags"][source][normalized["tag_id"]] = normalized


class OfflineFusionRunner:
    def __init__(self) -> None:
        self.radar_history: list[dict] = []
        self.kalman_trackers = {"named": {}, "clusters": {}, "next_cluster_id": 1}
        self.last_publish_at: float | None = None

    def build_frame_payload(self, now: float) -> dict:
        if self.last_publish_at is None:
            self.last_publish_at = now - fusion.FUSED_PUBLISH_INTERVAL_SECONDS

        new_radar_points = list(fusion.shared_state["radar_points"])
        fusion.shared_state["radar_points"].clear()

        for sensor_id in ("ble_1", "ble_2"):
            fusion.shared_state["ble_tags"][sensor_id] = {
                tag_id: tag
                for tag_id, tag in fusion.shared_state["ble_tags"][sensor_id].items()
                if now - tag.get("_seen_at", tag.get("timestamp", now)) <= fusion.BLE_TAG_TTL_SECONDS
            }

        ble_1_tags = fusion.shared_state["ble_tags"]["ble_1"]
        ble_2_tags = fusion.shared_state["ble_tags"]["ble_2"]
        ble_1_ids = sorted(ble_1_tags.keys())
        ble_2_ids = sorted(ble_2_tags.keys())
        out_ble_1_raw = fusion.build_ble_debug_rays("ble_1", ble_1_tags)
        out_ble_2_raw = fusion.build_ble_debug_rays("ble_2", ble_2_tags)

        common_tags = set(ble_1_tags.keys()) & set(ble_2_tags.keys())
        common_tag_ids = sorted(common_tags)
        out_ble = []
        for tag_id in common_tags:
            position = fusion.triangulate_3d(tag_id)
            if position:
                out_ble.append({"tag_id": tag_id, "x": position["x"], "y": position["y"], "z": position["z"]})

        for point in new_radar_points:
            enriched = dict(point)
            enriched["_seen_at"] = now
            self.radar_history.append(enriched)

        self.radar_history = [
            point
            for point in self.radar_history
            if now - point.get("_seen_at", now) <= fusion.RAW_RADAR_HISTORY_SECONDS
        ][-fusion.MAX_RAW_RADAR_HISTORY_POINTS :]

        out_radar = [{key: value for key, value in point.items() if key != "_seen_at"} for point in self.radar_history]
        out_radar_payload = out_radar[-fusion.MAX_RADAR_POINTS_IN_MQTT_PAYLOAD :]
        out_clusters = fusion.cluster_radar_points(out_radar)
        out_objects, paired_count = fusion.build_fused_objects(out_clusters, out_ble, now)
        out_objects = fusion.apply_kalman_tracking(
            out_objects,
            self.kalman_trackers,
            now,
            now - self.last_publish_at,
        )
        self.last_publish_at = now

        return {
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
                "pair_max_distance": fusion.RADAR_BLE_PAIR_MAX_DISTANCE,
                "pair_hold_seconds": fusion.RADAR_BLE_PAIR_HOLD_SECONDS,
                "pair_reacquire_distance": fusion.RADAR_BLE_REACQUIRE_DISTANCE,
                "pair_lock_max_distance": fusion.RADAR_BLE_LOCK_MAX_DISTANCE,
                "pair_z_weight": fusion.RADAR_BLE_Z_WEIGHT,
                "pair_coast_seconds": fusion.RADAR_BLE_COAST_SECONDS,
                "ble_only_objects": sum(1 for obj in out_objects if obj["source"] == "ble_only"),
                "radar_ble_coasting_objects": sum(1 for obj in out_objects if obj["source"] == "radar_ble_coasting"),
                "radar_cluster_objects": sum(1 for obj in out_objects if obj["source"] == "radar_cluster"),
                "ble_1_tags": len(ble_1_tags),
                "ble_2_tags": len(ble_2_tags),
                "common_ble_tags": len(common_tags),
                "ble_1_ids": ble_1_ids,
                "ble_2_ids": ble_2_ids,
                "common_ble_ids": common_tag_ids,
                "triangulated_ble": len(out_ble),
            },
        }


def run_single_scenario(scenario_dir: Path) -> dict:
    raw_path = scenario_dir / "raw.ndjson"
    if not raw_path.exists():
        raise FileNotFoundError(f"Ve scenari {scenario_dir} chybi raw.ndjson")

    raw_records = list(iter_ndjson_records(raw_path))
    if not raw_records:
        raise ValueError(f"Soubor {raw_path} je prazdny.")

    reset_fusion_state()
    runner = OfflineFusionRunner()
    first_ts = float(raw_records[0].get("recorded_at") or raw_records[0].get("payload_timestamp") or 0.0)
    last_ts = float(raw_records[-1].get("recorded_at") or raw_records[-1].get("payload_timestamp") or 0.0)
    current_ts = first_ts
    record_index = 0
    fused_count = 0
    fused_output_path = scenario_dir / "fused.ndjson"
    temp_output_path = scenario_dir / "fused.ndjson.tmp"

    with temp_output_path.open("w", encoding="utf-8") as handle:
        while current_ts <= last_ts + fusion.FUSED_PUBLISH_INTERVAL_SECONDS + 1e-9:
            while record_index < len(raw_records):
                record_ts = float(
                    raw_records[record_index].get("recorded_at")
                    or raw_records[record_index].get("payload_timestamp")
                    or 0.0
                )
                if record_ts > current_ts + 1e-9:
                    break
                ingest_raw_record(raw_records[record_index])
                record_index += 1

            payload = runner.build_frame_payload(current_ts)
            ndjson_record = {
                "recorded_at": current_ts,
                "topic": "sensors/fused",
                "payload_text": json.dumps(payload, ensure_ascii=False),
                "payload_timestamp": current_ts,
            }
            write_ndjson_record(handle, ndjson_record)
            fused_count += 1
            current_ts += fusion.FUSED_PUBLISH_INTERVAL_SECONDS

    temp_output_path.replace(fused_output_path)

    metadata_path = scenario_dir / "metadata.json"
    metadata = {}
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update(
        {
            "raw_file": "raw.ndjson",
            "fused_file": "fused.ndjson",
            "fused_messages": fused_count,
            "fused_generated_offline": True,
            "fused_publish_interval_seconds": fusion.FUSED_PUBLISH_INTERVAL_SECONDS,
            "started_at": first_ts,
            "ended_at": last_ts,
            "duration_seconds": last_ts - first_ts,
        }
    )
    write_json(metadata_path, metadata)

    summary = {
        "scenario_dir": str(scenario_dir),
        "raw_path": str(raw_path),
        "fused_path": str(fused_output_path),
        "raw_messages": len(raw_records),
        "fused_messages": fused_count,
        "started_at": first_ts,
        "ended_at": last_ts,
    }
    write_json(scenario_dir / "offline_fusion_summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir = resolve_run_dir(args.run_dir)
    scenario_root = resolve_scenario_root(args.scenario_root, run_dir=run_dir)

    if not scenario_root.exists():
        raise FileNotFoundError(f"Scenario root neexistuje: {scenario_root}")

    requested = list(dict.fromkeys(args.scenarios))
    unknown = [name for name in requested if name not in SCENARIO_TOPICS]
    if unknown:
        raise ValueError(f"Neznamy scenar: {', '.join(unknown)}")

    all_results = {}
    for scenario_name in requested:
        scenario_dir = scenario_root / scenario_name
        result = run_single_scenario(scenario_dir)
        all_results[scenario_name] = result
        print(f"Offline fusion hotova pro {scenario_name}: {result['fused_messages']} fused framu")

    write_json(
        scenario_root / "offline_fusion_summary.json",
        {
            "scenario_root": str(scenario_root),
            "results": all_results,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
