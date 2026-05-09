"""Spolecne definice pro offline porovnani scenaru senzoru."""

from __future__ import annotations

from collections import OrderedDict
import json
from pathlib import Path
from typing import Iterable


PROJECT_DIR = Path(__file__).resolve().parents[1]
RUNS_EXPERIMENT_DIR = PROJECT_DIR / "runs" / "experiment"
DEFAULT_SCENARIO_ROOT_NAME = "scenario_splits"
DEFAULT_OPTITRACK_CSV = PROJECT_DIR / "data" / "optitrack" / "Take_2026-05-07_12.43.55_PM_Final.csv"

SCENARIO_TOPICS = OrderedDict(
    [
        ("ble1", ("sensors/raw/ble_1",)),
        ("ble2", ("sensors/raw/ble_2",)),
        ("radar1", ("sensors/raw/radar_1",)),
        ("radar2", ("sensors/raw/radar_2",)),
        ("2x_radar", ("sensors/raw/radar_1", "sensors/raw/radar_2")),
        ("2x_ble", ("sensors/raw/ble_1", "sensors/raw/ble_2")),
        ("radar1_2x_ble", ("sensors/raw/radar_1", "sensors/raw/ble_1", "sensors/raw/ble_2")),
        ("radar2_2x_ble", ("sensors/raw/radar_2", "sensors/raw/ble_1", "sensors/raw/ble_2")),
        (
            "fusion",
            ("sensors/raw/ble_1", "sensors/raw/ble_2", "sensors/raw/radar_1", "sensors/raw/radar_2"),
        ),
    ]
)
ALL_RAW_TOPICS = {topic for topics in SCENARIO_TOPICS.values() for topic in topics}


def resolve_latest_run_dir() -> Path:
    if not RUNS_EXPERIMENT_DIR.exists():
        raise FileNotFoundError(f"Adresar s experimenty neexistuje: {RUNS_EXPERIMENT_DIR}")

    candidates = [path for path in RUNS_EXPERIMENT_DIR.iterdir() if path.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"V {RUNS_EXPERIMENT_DIR} neni zadna slozka experimentu.")

    preferred = [path for path in candidates if "dronarena" in path.name.lower()]
    return max(preferred or candidates, key=lambda path: path.name)


def resolve_run_dir(run_dir: str | Path | None = None, raw_path: str | Path | None = None) -> Path:
    if run_dir is not None:
        return Path(run_dir).resolve()
    if raw_path is not None:
        return Path(raw_path).resolve().parent
    return resolve_latest_run_dir().resolve()


def resolve_raw_path(raw_path: str | Path | None = None, run_dir: str | Path | None = None) -> Path:
    if raw_path is not None:
        return Path(raw_path).resolve()
    return resolve_run_dir(run_dir=run_dir) / "raw.ndjson"


def resolve_scenario_root(
    scenario_root: str | Path | None = None,
    *,
    run_dir: str | Path | None = None,
    raw_path: str | Path | None = None,
) -> Path:
    if scenario_root is not None:
        return Path(scenario_root).resolve()
    return resolve_run_dir(run_dir=run_dir, raw_path=raw_path) / DEFAULT_SCENARIO_ROOT_NAME


def load_metadata(run_dir: Path) -> dict:
    metadata_path = run_dir / "metadata.json"
    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iter_ndjson_records(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                yield json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Soubor {path} obsahuje neplatny JSON na radku {line_number}: {exc}") from exc


def write_ndjson_record(handle, payload: dict) -> None:
    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
