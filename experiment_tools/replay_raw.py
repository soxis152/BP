"""Replay raw MQTT zaznamu z predchoziho experimentu."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import threading
import time

import paho.mqtt.client as mqtt
import uvicorn


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = PROJECT_DIR.parent
RUNS_BASE_DIR = PROJECT_DIR

for candidate in (PROJECT_ROOT, PROJECT_DIR, SCRIPT_DIR):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

try:
    from Four.config import BASE_DIR, MQTT_HOST, MQTT_PORT
    from Four.run_context import set_current_run_id
except ImportError:
    try:
        from config import BASE_DIR, MQTT_HOST, MQTT_PORT
        from run_context import set_current_run_id
    except ImportError:
        from ..config import BASE_DIR, MQTT_HOST, MQTT_PORT
        from ..run_context import set_current_run_id

try:
    from Four import app as web_app
    from Four import fusion
    from Four.experiment_tools import optitrack_replay
except ImportError:
    try:
        import app as web_app
        import fusion
        from experiment_tools import optitrack_replay
    except ImportError:
        from .. import app as web_app
        from .. import fusion
        from . import optitrack_replay


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prehraje raw.ndjson zpet do MQTT.")
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Adresar experimentu s raw.ndjson. Kdyz chybi, pouzije se posledni slozka v runs/experiment.",
    )
    parser.add_argument("--host", default=MQTT_HOST, help="MQTT host.")
    parser.add_argument("--port", type=int, default=MQTT_PORT, help="MQTT port.")
    parser.add_argument("--rate", type=float, default=1.0, help="Rychlost prehravani. 1.0 = realny cas.")
    parser.add_argument("--loop", action="store_true", help="Po dojeti zacit znovu od zacatku.")
    parser.add_argument("--max-records", type=int, default=0, help="Volitelne omezeni poctu prehranych zprav.")
    parser.add_argument(
        "--start-local-stack",
        action="store_true",
        default=True,
        help="Pred replayem rozjede lokalni fusion + API ve stejnem procesu. Vychozi je zapnuto.",
    )
    parser.add_argument(
        "--no-local-stack",
        action="store_false",
        dest="start_local_stack",
        help="Vypne automaticky start lokalni fusion + API vrstvy.",
    )
    parser.add_argument("--api-host", default="127.0.0.1", help="Host pro lokalni API server.")
    parser.add_argument("--api-port", type=int, default=8000, help="Port pro lokalni API server.")
    parser.add_argument(
        "--startup-wait",
        type=float,
        default=3.0,
        help="Kolik sekund pockat po startu lokalniho fusion/API pred replayem.",
    )
    parser.add_argument(
        "--with-optitrack-reference",
        action="store_true",
        help="Soucasne pusti i OptiTrack referenci do samostatneho dashboard modu.",
    )
    parser.add_argument(
        "--optitrack-input",
        default=None,
        help="Volitelna cesta k OptiTrack exportu (.csv/.xlsx). Kdyz chybi, pouzije se default optitrack_replay.",
    )
    parser.add_argument("--optitrack-sheet", default=None, help="Volitelny sheet OptiTrack XLSX.")
    parser.add_argument("--optitrack-rate", type=float, default=None, help="Rychlost OptiTrack reference. Vychozi kopiruje --rate.")
    parser.add_argument("--optitrack-frame-stride", type=int, default=1, help="Pouzit kazdy N-ty frame OptiTracku.")
    parser.add_argument("--optitrack-max-frames", type=int, default=0, help="Volitelne omezeni poctu OptiTrack framu.")
    parser.add_argument("--optitrack-loop", action="store_true", help="Loop OptiTrack reference nezavisle na raw replay.")
    parser.add_argument("--optitrack-delay-sec", type=float, default=0.0, help="Kolik sekund cekat pred prvnim OptiTrack framem.")
    parser.add_argument("--optitrack-start-on-body", default=optitrack_replay.DEFAULT_START_ON_BODY, help="Rigid body, na kterem ma OptiTrack reference zacit.")
    parser.add_argument("--optitrack-axis-x", default=optitrack_replay.DEFAULT_AXIS_X, help="Mapovani OptiTrack osy na systemovou X.")
    parser.add_argument("--optitrack-axis-y", default=optitrack_replay.DEFAULT_AXIS_Y, help="Mapovani OptiTrack osy na systemovou Y.")
    parser.add_argument("--optitrack-axis-z", default=optitrack_replay.DEFAULT_AXIS_Z, help="Mapovani OptiTrack osy na systemovou Z.")
    parser.add_argument("--optitrack-yaw-deg", type=float, default=optitrack_replay.DEFAULT_YAW_DEG, help="Rotace OptiTrack reference v rovine XY.")
    parser.add_argument("--optitrack-offset-x", type=float, default=optitrack_replay.DEFAULT_OFFSET_X, help="Posun OptiTrack reference v ose X.")
    parser.add_argument("--optitrack-offset-y", type=float, default=optitrack_replay.DEFAULT_OFFSET_Y, help="Posun OptiTrack reference v ose Y.")
    parser.add_argument("--optitrack-offset-z", type=float, default=optitrack_replay.DEFAULT_OFFSET_Z, help="Posun OptiTrack reference v ose Z.")
    return parser.parse_args(argv)


def resolve_latest_run_dir() -> Path:
    experiment_root = RUNS_BASE_DIR / "runs" / "experiment"
    if not experiment_root.exists():
        raise FileNotFoundError(f"Adresar s experimenty neexistuje: {experiment_root}")

    candidates = [path for path in experiment_root.iterdir() if path.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"V {experiment_root} neni zadna slozka experimentu.")

    return max(candidates, key=lambda path: path.name)


def resolve_preferred_run_dir() -> Path:
    experiment_root = RUNS_BASE_DIR / "runs" / "experiment"
    candidates = [path for path in experiment_root.iterdir() if path.is_dir()]
    dronarena_candidates = [path for path in candidates if "dronarena" in path.name.lower()]
    if dronarena_candidates:
        return max(dronarena_candidates, key=lambda path: path.name)
    return resolve_latest_run_dir()


def resolve_run_dir(input_dir: str | None) -> Path:
    if input_dir:
        return Path(input_dir).resolve()
    return resolve_preferred_run_dir().resolve()


def load_records(raw_path: Path):
    records = []
    with raw_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    if not records:
        raise ValueError(f"Soubor {raw_path} neobsahuje zadne raw zpravy.")
    return records


def load_metadata(run_dir: Path) -> dict:
    metadata_path = run_dir / "metadata.json"
    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def start_fusion_thread() -> threading.Thread:
    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(fusion.main_fusion())
        finally:
            loop.close()

    thread = threading.Thread(target=runner, name="replay_fusion_thread", daemon=True)
    thread.start()
    return thread


def start_api_thread(host: str, port: int) -> threading.Thread:
    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        config = uvicorn.Config(web_app.app, host=host, port=port, reload=False, loop="asyncio")
        server = uvicorn.Server(config)
        loop.run_until_complete(server.serve())

    thread = threading.Thread(target=runner, name="replay_api_thread", daemon=True)
    thread.start()
    return thread


def maybe_start_local_stack(args: argparse.Namespace) -> None:
    if not args.start_local_stack:
        return

    print("Replay: startuji lokalni fusion vrstvu.")
    start_fusion_thread()
    print(f"Replay: startuji lokalni API na http://{args.api_host}:{args.api_port}")
    start_api_thread(args.api_host, args.api_port)

    if args.startup_wait > 0:
        print(f"Replay: cekam {args.startup_wait:.1f}s na nabeh lokalniho stacku.")
        time.sleep(args.startup_wait)


def start_optitrack_reference_thread(args: argparse.Namespace) -> threading.Thread:
    optitrack_args = argparse.Namespace(
        input_path=args.optitrack_input or str(optitrack_replay.DEFAULT_XLSX),
        sheet=args.optitrack_sheet,
        objects=None,
        axis_x=args.optitrack_axis_x,
        axis_y=args.optitrack_axis_y,
        axis_z=args.optitrack_axis_z,
        yaw_deg=args.optitrack_yaw_deg,
        offset_x=args.optitrack_offset_x,
        offset_y=args.optitrack_offset_y,
        offset_z=args.optitrack_offset_z,
        auto_fit_room=False,
        room_size_x=3.0,
        room_size_y=3.0,
        room_margin=0.35,
        floor_z=0.15,
        speed=args.optitrack_rate or args.rate,
        frame_stride=max(1, args.optitrack_frame_stride),
        max_frames=max(0, args.optitrack_max_frames),
        loop=args.optitrack_loop or args.loop,
        initial_delay_sec=max(0.0, args.optitrack_delay_sec),
        publish_mode="direct",
        start_on_body=args.optitrack_start_on_body,
        start_local_stack=False,
        api_host=args.api_host,
        api_port=args.api_port,
        startup_wait=0.0,
    )

    def runner():
        asyncio.run(optitrack_replay.run_replay(optitrack_args))

    thread = threading.Thread(target=runner, name="replay_optitrack_reference_thread", daemon=True)
    thread.start()
    return thread


def replay_once(client: mqtt.Client, records, rate: float) -> None:
    first_recorded_at = records[0]["recorded_at"]
    started_monotonic = time.monotonic()

    for index, record in enumerate(records, start=1):
        target_delay = max(0.0, (record["recorded_at"] - first_recorded_at) / max(rate, 0.001))
        while True:
            remaining = target_delay - (time.monotonic() - started_monotonic)
            if remaining <= 0:
                break
            time.sleep(min(remaining, 0.01))

        info = client.publish(record["topic"], record["payload_text"])
        info.wait_for_publish()

        if index % 500 == 0:
            print(f"Replay: publikovano {index} raw zprav.")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    run_dir = resolve_run_dir(args.input_dir)
    raw_path = run_dir / "raw.ndjson"

    if args.input_dir:
        print(f"Replay: pouzivam experiment {run_dir}", flush=True)
    else:
        print(f"Replay: --input-dir nebyl zadany, pouzivam preferovany experiment {run_dir}", flush=True)

    maybe_start_local_stack(args)

    print(f"Replay: nacitam raw zaznam z {raw_path}", flush=True)
    records = load_records(raw_path)
    metadata = load_metadata(run_dir)
    if args.max_records > 0:
        records = records[: args.max_records]

    run_id = str(metadata.get("run_id", run_dir.name)).strip()
    if run_id:
        active_run_id = set_current_run_id(run_id)
        print(f"Replay: aktivni run_id = {active_run_id}", flush=True)

    if args.with_optitrack_reference:
        print("Replay: startuji soubezne OptiTrack referenci do samostatneho dashboard modu.", flush=True)
        start_optitrack_reference_thread(args)

    client = mqtt.Client(client_id="four_raw_replay")
    client.connect(args.host, args.port)
    client.loop_start()

    print(f"Replay: nacteno {len(records)} raw zprav z {raw_path}", flush=True)
    print(f"Replay: host={args.host}:{args.port}, rate={args.rate}", flush=True)

    try:
        iteration = 0
        while True:
            iteration += 1
            print(f"Replay: iterace {iteration} start.")
            replay_once(client, records, args.rate)
            print("Replay: iterace dokoncena.")
            if not args.loop:
                break
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nReplay stopped.")
