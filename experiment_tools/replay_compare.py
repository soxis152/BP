"""Jednim souborem spusti raw replay i OptiTrack porovnani v dashboard modu."""

from __future__ import annotations

import os
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = PROJECT_DIR.parent

try:
    from Four.experiment_tools.compare_defaults import DRONARENA_04_PROFILE, build_replay_reference_args
except ImportError:
    try:
        from experiment_tools.compare_defaults import DRONARENA_04_PROFILE, build_replay_reference_args
    except ImportError:
        from compare_defaults import DRONARENA_04_PROFILE, build_replay_reference_args


def build_default_args() -> list[str]:
    args = [
        "--input-dir",
        str(DRONARENA_04_PROFILE.run_dir),
    ]
    args.extend(build_replay_reference_args(DRONARENA_04_PROFILE))
    return args


def import_replay_raw_main():
    os.environ.setdefault("FOUR_DASHBOARD_DEFAULT_DATA_MODE", "fused_opti")

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

    print("Spoustim synchronizovany replay Fused+OptiTrack v dashboard modu Fused+Opti...")
    print("Dashboard: http://127.0.0.1:8000/")
    replay_raw_main(effective_args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nReplay_compare prerusen uzivatelem.")
