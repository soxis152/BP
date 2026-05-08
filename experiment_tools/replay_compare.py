"""Jednim souborem spusti raw replay i OptiTrack porovnani v dashboard modu."""

from __future__ import annotations

import os
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = PROJECT_DIR.parent
PREFERRED_OPTITRACK_INPUT = PROJECT_DIR / "data" / "optitrack" / "Take 2026-05-07 12.43.55 PM.csv"
PREFERRED_EXPERIMENT_INPUT_DIR = PROJECT_DIR / "runs" / "experiment" / "20260507_104346_Dronarena_04"


def build_default_args() -> list[str]:
    args = [

        "--input-dir",
        str(PREFERRED_EXPERIMENT_INPUT_DIR),

        # Pro mereni Dronarena_04           # pro mereni Dronarena_02

        "--with-optitrack-reference",

        # Casovy offset
        "--optitrack-delay-sec",
        "7.376",                              # "97.5",

        # Souradnice
        "--optitrack-axis-x",
        "z",
        "--optitrack-axis-y",
        "x",
        "--optitrack-axis-z",
        "y",

        # Prostorove offsety
        "--optitrack-yaw-deg",
        "0",
        "--optitrack-offset-x",
        "2.371",                              # "2.635",
        "--optitrack-offset-y",
        "3.808",                              # "3.847",
        "--optitrack-offset-z",
        "0.068",

    ]

    if PREFERRED_OPTITRACK_INPUT.exists():
        args.extend(["--optitrack-input", str(PREFERRED_OPTITRACK_INPUT)])

    return args


def import_replay_raw_main():
    os.environ.setdefault("FOUR_DASHBOARD_DEFAULT_DATA_MODE", "raw_opti")

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    if str(PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    try:
        from Four.experiment_tools.replay_raw import main as replay_raw_main
        return replay_raw_main
    except ImportError:
        try:
            from experiment_tools.replay_raw import main as replay_raw_main
            return replay_raw_main
        except ImportError:
            from replay_raw import main as replay_raw_main
            return replay_raw_main


def main(argv: list[str] | None = None) -> None:
    replay_raw_main = import_replay_raw_main()
    effective_args = build_default_args() + list(argv or sys.argv[1:])

    print("Spoustim synchronizovany replay Raw+OptiTrack v dashboard modu Raw+Opti...")
    print("Dashboard: http://127.0.0.1:8000/")
    replay_raw_main(effective_args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nReplay_compare prerusen uzivatelem.")
