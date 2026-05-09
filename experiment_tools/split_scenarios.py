"""Rozdeli hlavni raw.ndjson do scenaru podle pouzitych topicu."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = PROJECT_DIR.parent

for candidate in (PROJECT_ROOT, PROJECT_DIR, SCRIPT_DIR):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

try:
    from Four.experiment_tools.scenario_pipeline_common import (
        ALL_RAW_TOPICS,
        SCENARIO_TOPICS,
        iter_ndjson_records,
        load_metadata,
        resolve_raw_path,
        resolve_run_dir,
        resolve_scenario_root,
        write_json,
        write_ndjson_record,
    )
except ImportError:
    try:
        from experiment_tools.scenario_pipeline_common import (
            ALL_RAW_TOPICS,
            SCENARIO_TOPICS,
            iter_ndjson_records,
            load_metadata,
            resolve_raw_path,
            resolve_run_dir,
            resolve_scenario_root,
            write_json,
            write_ndjson_record,
        )
    except ImportError:
        from scenario_pipeline_common import (
            ALL_RAW_TOPICS,
            SCENARIO_TOPICS,
            iter_ndjson_records,
            load_metadata,
            resolve_raw_path,
            resolve_run_dir,
            resolve_scenario_root,
            write_json,
            write_ndjson_record,
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rozdeli zdrojovy raw.ndjson do scenaru senzoru.")
    parser.add_argument("--raw", default=None, help="Cesta ke zdrojovemu raw.ndjson.")
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Adresar behu s raw.ndjson. Kdyz chybi i --raw, pouzije se posledni experiment.",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help="Root adresar, do ktereho se vytvori podslozky scenaru. Vychozi: <run-dir>/scenario_splits.",
    )
    return parser.parse_args(argv)


def build_topic_to_scenarios() -> dict[str, list[str]]:
    topic_to_scenarios: dict[str, list[str]] = defaultdict(list)
    for scenario_name, topics in SCENARIO_TOPICS.items():
        for topic in topics:
            topic_to_scenarios[topic].append(scenario_name)
    return topic_to_scenarios


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    raw_path = resolve_raw_path(args.raw, args.run_dir)
    run_dir = resolve_run_dir(args.run_dir, raw_path)
    output_root = resolve_scenario_root(args.output_root, run_dir=run_dir, raw_path=raw_path)

    if not raw_path.exists():
        raise FileNotFoundError(f"Zdrojovy raw.ndjson nebyl nalezen: {raw_path}")

    output_root.mkdir(parents=True, exist_ok=True)
    source_metadata = load_metadata(run_dir)
    topic_to_scenarios = build_topic_to_scenarios()

    handles = {}
    temp_paths = {}
    raw_counts = {scenario_name: 0 for scenario_name in SCENARIO_TOPICS}
    topic_counts = {scenario_name: defaultdict(int) for scenario_name in SCENARIO_TOPICS}
    first_recorded_at = {scenario_name: None for scenario_name in SCENARIO_TOPICS}
    last_recorded_at = {scenario_name: None for scenario_name in SCENARIO_TOPICS}

    try:
        for scenario_name in SCENARIO_TOPICS:
            scenario_dir = output_root / scenario_name
            scenario_dir.mkdir(parents=True, exist_ok=True)
            temp_path = scenario_dir / "raw.ndjson.tmp"
            temp_paths[scenario_name] = temp_path
            handles[scenario_name] = temp_path.open("w", encoding="utf-8")

        for record in iter_ndjson_records(raw_path):
            topic = str(record.get("topic", "")).strip()
            if topic not in ALL_RAW_TOPICS:
                continue

            scenario_names = topic_to_scenarios.get(topic, ())
            if not scenario_names:
                continue

            recorded_at = float(record.get("recorded_at") or 0.0)
            for scenario_name in scenario_names:
                write_ndjson_record(handles[scenario_name], record)
                raw_counts[scenario_name] += 1
                topic_counts[scenario_name][topic] += 1
                if first_recorded_at[scenario_name] is None:
                    first_recorded_at[scenario_name] = recorded_at
                last_recorded_at[scenario_name] = recorded_at
    finally:
        for handle in handles.values():
            handle.close()

    summary = {
        "source_raw": str(raw_path),
        "source_run_dir": str(run_dir),
        "scenario_root": str(output_root),
        "scenarios": {},
    }

    for scenario_name, topics in SCENARIO_TOPICS.items():
        scenario_dir = output_root / scenario_name
        raw_output_path = scenario_dir / "raw.ndjson"
        temp_paths[scenario_name].replace(raw_output_path)

        scenario_metadata = dict(source_metadata)
        scenario_metadata.update(
            {
                "scenario": scenario_name,
                "scenario_topics": list(topics),
                "scenario_source_raw": str(raw_path),
                "raw_file": "raw.ndjson",
                "fused_file": "fused.ndjson",
                "raw_messages": raw_counts[scenario_name],
                "started_at": first_recorded_at[scenario_name],
                "ended_at": last_recorded_at[scenario_name],
                "duration_seconds": (
                    None
                    if first_recorded_at[scenario_name] is None or last_recorded_at[scenario_name] is None
                    else last_recorded_at[scenario_name] - first_recorded_at[scenario_name]
                ),
                "topic_counts": dict(topic_counts[scenario_name]),
            }
        )
        write_json(scenario_dir / "metadata.json", scenario_metadata)

        summary["scenarios"][scenario_name] = {
            "dir": str(scenario_dir),
            "raw_messages": raw_counts[scenario_name],
            "topics": list(topics),
            "topic_counts": dict(topic_counts[scenario_name]),
        }

    write_json(output_root / "split_summary.json", summary)
    print(f"Split hotov: {raw_path} -> {output_root}")
    for scenario_name, info in summary["scenarios"].items():
        print(f"- {scenario_name}: {info['raw_messages']} raw zpráv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
