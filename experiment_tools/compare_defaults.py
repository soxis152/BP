"""Sdilena konfigurace compare/evaluate workflow pro konkretni replay profily."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = PROJECT_DIR.parent


@dataclass(frozen=True)
class CompareProfile:
    run_dir: Path
    optitrack_input: Path
    start_on_body: str
    replay_delay_sec: float
    axis_x: str
    axis_y: str
    axis_z: str
    yaw_deg: float
    offset_x: float
    offset_y: float
    offset_z: float
    phantom_tag_id: str
    vacuum_tag_id: str


DRONARENA_04_PROFILE = CompareProfile(
    run_dir=PROJECT_DIR / "runs" / "experiment" / "20260507_104346_Dronarena_04",
    optitrack_input=PROJECT_DIR / "data" / "optitrack" / "Take_2026-05-07_12.43.55_PM_Final.csv",
    start_on_body="Phantom4",
    replay_delay_sec=7.376,
    axis_x="z",
    axis_y="x",
    axis_z="y",
    yaw_deg=0.0,
    offset_x=2.371,
    offset_y=3.808,
    offset_z=0.068,
    phantom_tag_id="20BA360ABBB8",
    vacuum_tag_id="20BA360ABB32",
)


def _ensure_import_paths() -> None:
    for candidate in (PROJECT_ROOT, PROJECT_DIR, SCRIPT_DIR):
        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)


def _import_load_optitrack_take():
    _ensure_import_paths()
    try:
        from Four.experiment_tools.optitrack_xlsx import load_optitrack_take
        return load_optitrack_take
    except ImportError:
        try:
            from experiment_tools.optitrack_xlsx import load_optitrack_take
            return load_optitrack_take
        except ImportError:
            from optitrack_xlsx import load_optitrack_take
            return load_optitrack_take


def resolve_tag_map(profile: CompareProfile) -> list[tuple[str, str]]:
    if not profile.optitrack_input.exists():
        return []

    load_optitrack_take = _import_load_optitrack_take()
    take = load_optitrack_take(profile.optitrack_input)
    body_names = [body.name for body in take.rigid_bodies]
    upper_map = {name.upper(): name for name in body_names}

    mapping: list[tuple[str, str]] = []
    phantom_name = upper_map.get("PHANTOM4")
    vacuum_name = next((name for name in body_names if name.upper().startswith("VYSAVAC")), None)

    if phantom_name:
        mapping.append((profile.phantom_tag_id, phantom_name))
    if vacuum_name:
        mapping.append((profile.vacuum_tag_id, vacuum_name))
    return mapping


def resolve_replay_compare_time_offset(profile: CompareProfile) -> float | None:
    if not profile.optitrack_input.exists():
        return None

    load_optitrack_take = _import_load_optitrack_take()
    take = load_optitrack_take(profile.optitrack_input)
    first_visible_time = next(
        (frame.time_seconds for frame in take.frames if profile.start_on_body in frame.bodies),
        None,
    )
    if first_visible_time is None:
        return None
    return float(first_visible_time) - profile.replay_delay_sec


def build_replay_reference_args(profile: CompareProfile) -> list[str]:
    args = [
        "--with-optitrack-reference",
        "--optitrack-delay-sec",
        f"{profile.replay_delay_sec}",
        "--optitrack-start-on-body",
        profile.start_on_body,
        "--optitrack-axis-x",
        profile.axis_x,
        "--optitrack-axis-y",
        profile.axis_y,
        "--optitrack-axis-z",
        profile.axis_z,
        "--optitrack-yaw-deg",
        f"{profile.yaw_deg}",
        "--optitrack-offset-x",
        f"{profile.offset_x}",
        "--optitrack-offset-y",
        f"{profile.offset_y}",
        "--optitrack-offset-z",
        f"{profile.offset_z}",
    ]
    if profile.optitrack_input.exists():
        args.extend(["--optitrack-input", str(profile.optitrack_input)])
    return args


def build_evaluation_reference_args(profile: CompareProfile) -> list[str]:
    args = [
        "--axis-x",
        profile.axis_x,
        "--axis-y",
        profile.axis_y,
        "--axis-z",
        profile.axis_z,
        "--yaw-deg",
        f"{profile.yaw_deg}",
        "--offset-x",
        f"{profile.offset_x}",
        "--offset-y",
        f"{profile.offset_y}",
        "--offset-z",
        f"{profile.offset_z}",
    ]

    if profile.optitrack_input.exists():
        args.extend(["--xlsx", str(profile.optitrack_input)])
        for tag_id, body_name in resolve_tag_map(profile):
            args.extend(["--tag-map", f"{tag_id}={body_name}"])
        time_offset = resolve_replay_compare_time_offset(profile)
        if time_offset is not None:
            args.extend(["--time-offset", f"{time_offset:.6f}"])

    return args
