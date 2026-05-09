"""Replay raw MQTT zaznamu z predchoziho experimentu."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import socket
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
        "--use-frame-cache",
        action="store_true",
        default=True,
        help="Kdyz existuje replay_frames.ndjson, dashboard ho preloadne misto ziveho replaye.",
    )
    parser.add_argument(
        "--no-frame-cache",
        action="store_false",
        dest="use_frame_cache",
        help="Ignoruje existujici replay frame cache a pousti normalni raw replay.",
    )
    parser.add_argument(
        "--rebuild-frame-cache",
        action="store_true",
        help="Vynuti zivy replay a po jeho dokonceni prepise replay frame cache.",
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


def get_frame_cache_path(run_dir: Path) -> Path:
    return run_dir / "replay_frames.ndjson"


def get_fused_dataset_path(run_dir: Path) -> Path:
    return run_dir / "fused.ndjson"


def get_timeline_dataset_path(run_dir: Path) -> Path:
    return run_dir / "replay_timeline.ndjson"


def get_timeline_metadata_path(run_dir: Path) -> Path:
    return run_dir / "replay_timeline.meta.json"


def resolve_preload_dataset_path(run_dir: Path) -> Path | None:
    preferred_paths = [
        get_fused_dataset_path(run_dir),
        get_frame_cache_path(run_dir),
    ]
    for candidate in preferred_paths:
        if candidate.exists():
            return candidate
    return None


def count_ndjson_records(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def build_file_state(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def build_timeline_signature(
    run_dir: Path,
    metadata: dict,
    args: argparse.Namespace,
    optitrack_input: Path,
) -> dict[str, object]:
    fused_dataset_path = get_fused_dataset_path(run_dir)
    return {
        "run_dir": str(run_dir.resolve()),
        "optitrack_input": build_file_state(optitrack_input),
        "fused_dataset": build_file_state(fused_dataset_path),
        "builder": {
            "optitrack_sheet": args.optitrack_sheet,
            "optitrack_axis_x": args.optitrack_axis_x,
            "optitrack_axis_y": args.optitrack_axis_y,
            "optitrack_axis_z": args.optitrack_axis_z,
            "optitrack_yaw_deg": args.optitrack_yaw_deg,
            "optitrack_offset_x": args.optitrack_offset_x,
            "optitrack_offset_y": args.optitrack_offset_y,
            "optitrack_offset_z": args.optitrack_offset_z,
            "optitrack_frame_stride": max(1, args.optitrack_frame_stride),
            "optitrack_max_frames": max(0, args.optitrack_max_frames),
            "optitrack_start_on_body": args.optitrack_start_on_body,
        },
        "run": {
            "run_id": metadata.get("run_id"),
            "fused_messages": metadata.get("fused_messages"),
        },
    }


def load_timeline_signature(run_dir: Path) -> dict[str, object] | None:
    metadata_path = get_timeline_metadata_path(run_dir)
    if not metadata_path.exists():
        return None
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_timeline_signature(run_dir: Path, signature: dict[str, object]) -> None:
    metadata_path = get_timeline_metadata_path(run_dir)
    metadata_path.write_text(
        json.dumps(signature, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def remove_timeline_cache(run_dir: Path) -> None:
    for path in (get_timeline_dataset_path(run_dir), get_timeline_metadata_path(run_dir)):
        if path.exists():
            path.unlink()


def resolve_bundle_optitrack_input(run_dir: Path, metadata: dict, args: argparse.Namespace) -> Path | None:
    if args.optitrack_input:
        candidate = Path(args.optitrack_input).resolve()
        return candidate if candidate.exists() else None

    data_dir = PROJECT_DIR / "data" / "optitrack"
    if not data_dir.exists():
        return None

    run_date_iso = str(metadata.get("started_at_iso", "")).split("T")[0].strip()
    if run_date_iso:
        mm_dd_yyyy = "-".join(reversed(run_date_iso.split("-")))
        dated_matches = sorted(
            path for path in data_dir.glob("*")
            if path.is_file()
            and path.suffix.lower() in {".csv", ".xlsx"}
            and (run_date_iso in path.name or mm_dd_yyyy in path.name)
        )
        if dated_matches:
            return dated_matches[-1]

    fallback = Path(optitrack_replay.DEFAULT_XLSX).resolve()
    if fallback.exists():
        return fallback
    return None


def is_timeline_cache_stale(run_dir: Path, metadata: dict, args: argparse.Namespace) -> tuple[bool, str | None]:
    timeline_path = get_timeline_dataset_path(run_dir)
    if not timeline_path.exists():
        return True, "timeline dataset chybi"

    optitrack_input = resolve_bundle_optitrack_input(run_dir, metadata, args)
    if not optitrack_input:
        return False, None

    expected_signature = build_timeline_signature(run_dir, metadata, args, optitrack_input)
    current_signature = load_timeline_signature(run_dir)
    if current_signature is None:
        return True, "timeline metadata chybi nebo jsou necitelna"
    if current_signature != expected_signature:
        return True, "zmenil se OptiTrack CSV, fused dataset nebo parametry timeline builderu"
    return False, None


def build_optitrack_objects_for_frame(take_frame) -> list[dict]:
    visible_objects = []
    for body_name, (x, y, z) in take_frame.bodies.items():
        visible_objects.append(
            {
                "tag_id": optitrack_replay.sanitize_tag_id(body_name),
                "object_type": "optitrack",
                "source": "optitrack",
                "x": round(x, 4),
                "y": round(y, 4),
                "z": round(z, 4),
                "confidence": 0.99,
            }
        )
    return visible_objects


def load_fused_timestamps(fused_dataset_path: Path) -> list[float]:
    timestamps = []
    with fused_dataset_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            timestamps.append(float(record.get("payload_timestamp") or record.get("recorded_at") or 0.0))
    if not timestamps:
        raise ValueError(f"Dataset {fused_dataset_path} neobsahuje zadne fused frame timestampy.")
    return timestamps


def find_nearest_timestamp_index(sorted_timestamps: list[float], target: float, start_index: int) -> int:
    index = max(0, min(len(sorted_timestamps) - 1, start_index))
    while index + 1 < len(sorted_timestamps):
        current_delta = abs(sorted_timestamps[index] - target)
        next_delta = abs(sorted_timestamps[index + 1] - target)
        if next_delta > current_delta:
            break
        index += 1
    return index


def build_replay_timeline_dataset(run_dir: Path, metadata: dict, args: argparse.Namespace) -> Path | None:
    fused_dataset_path = get_fused_dataset_path(run_dir)
    if not fused_dataset_path.exists():
        return None

    optitrack_input = resolve_bundle_optitrack_input(run_dir, metadata, args)
    if not optitrack_input:
        return None
    timeline_signature = build_timeline_signature(run_dir, metadata, args, optitrack_input)

    take = optitrack_replay.load_optitrack_take(
        optitrack_input,
        sheet_name=args.optitrack_sheet,
        axis_x=args.optitrack_axis_x,
        axis_y=args.optitrack_axis_y,
        axis_z=args.optitrack_axis_z,
        yaw_degrees=args.optitrack_yaw_deg,
        offset_x=args.optitrack_offset_x,
        offset_y=args.optitrack_offset_y,
        offset_z=args.optitrack_offset_z,
        selected_bodies=None,
    )

    frame_step = max(1, args.optitrack_frame_stride)
    selected_frames = optitrack_replay.trim_leading_frames(
        take.frames,
        start_on_body=args.optitrack_start_on_body,
    )[::frame_step]
    if args.optitrack_max_frames > 0:
        selected_frames = selected_frames[: args.optitrack_max_frames]
    if not selected_frames:
        return None

    fused_timestamps = load_fused_timestamps(fused_dataset_path)
    run_start_ts = fused_timestamps[0]
    first_frame_time = selected_frames[0].time_seconds
    output_path = get_timeline_dataset_path(run_dir)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    current_fused_index = 0
    with temp_path.open("w", encoding="utf-8") as handle:
        for index, take_frame in enumerate(selected_frames):
            relative_time = take_frame.time_seconds - first_frame_time
            target_timestamp = run_start_ts + relative_time
            current_fused_index = find_nearest_timestamp_index(
                fused_timestamps,
                target_timestamp,
                current_fused_index,
            )
            visible_objects = build_optitrack_objects_for_frame(take_frame)
            timeline_entry = {
                "frame_index": index,
                "frame_number": take_frame.frame_number,
                "time_seconds": round(relative_time, 6),
                "timestamp": target_timestamp,
                "fused_frame_index": current_fused_index,
                "optitrack_objects": visible_objects,
                "optitrack_stats": {
                    "timestamp": target_timestamp,
                    "objects": len(visible_objects),
                    "optitrack_objects": len(visible_objects),
                    "stream_label": "OptiTrack reference",
                    "frame_number": take_frame.frame_number,
                },
            }
            handle.write(json.dumps(timeline_entry, ensure_ascii=False) + "\n")

            if (index + 1) % 5000 == 0:
                print(f"Replay: timeline bundle {index + 1}/{len(selected_frames)} framu.", flush=True)

    temp_path.replace(output_path)
    save_timeline_signature(run_dir, timeline_signature)
    print(
        f"Replay: pripraven timeline dataset {output_path} "
        f"({len(selected_frames)} framu) z {optitrack_input.name}.",
        flush=True,
    )
    return output_path


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


def can_bind_tcp_port(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def find_available_tcp_port(host: str, preferred_port: int, search_span: int = 32) -> int:
    for port in range(preferred_port, preferred_port + max(1, search_span)):
        if can_bind_tcp_port(host, port):
            return port
    raise RuntimeError(
        f"Nepodarilo se najit volny TCP port pro API na {host} "
        f"v rozsahu {preferred_port}-{preferred_port + max(1, search_span) - 1}."
    )


def maybe_start_local_stack(args: argparse.Namespace) -> None:
    if not args.start_local_stack:
        return

    resolved_api_port = find_available_tcp_port(args.api_host, args.api_port)
    if resolved_api_port != args.api_port:
        print(
            f"Replay: API port {args.api_port} je obsazeny, prepinam na {resolved_api_port}.",
            flush=True,
        )
        args.api_port = resolved_api_port

    print("Replay: startuji lokalni fusion vrstvu.")
    start_fusion_thread()
    print(f"Replay: startuji lokalni API na http://{args.api_host}:{args.api_port}")
    start_api_thread(args.api_host, args.api_port)

    if args.startup_wait > 0:
        print(f"Replay: cekam {args.startup_wait:.1f}s na nabeh lokalniho stacku.")
        time.sleep(args.startup_wait)


def start_frame_cache_recorder(
    host: str,
    port: int,
    output_path: Path,
) -> dict:
    """Nahrava MQTT snapshoty do NDJSON cache pro pozdejsi preload dashboardu."""
    stop_event = threading.Event()
    ready_event = threading.Event()
    state = {"frames": 0, "latest_optitrack": {}}
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    def runner():
        if temp_path.exists():
            temp_path.unlink()

        with temp_path.open("w", encoding="utf-8") as handle:
            def on_connect(client, _userdata, _flags, _rc):
                client.subscribe("sensors/fused")
                client.subscribe(web_app.OPTITRACK_REFERENCE_TOPIC)
                ready_event.set()

            def on_message(_client, _userdata, message):
                try:
                    payload = json.loads(message.payload.decode())
                except Exception:
                    return

                topic = str(message.topic)
                if topic == web_app.OPTITRACK_REFERENCE_TOPIC:
                    state["latest_optitrack"] = payload
                    return

                if topic != "sensors/fused":
                    return

                merged_payload = dict(payload)
                optitrack_payload = state["latest_optitrack"] or {}
                merged_payload["optitrack_objects"] = list(optitrack_payload.get("objects", []))
                merged_payload["optitrack_stats"] = optitrack_payload.get("stats")
                handle.write(json.dumps(merged_payload, ensure_ascii=False) + "\n")
                handle.flush()
                state["frames"] += 1

            client = mqtt.Client(client_id=f"four_frame_cache_{int(time.time())}")
            client.on_connect = on_connect
            client.on_message = on_message
            client.connect(host, port)
            client.loop_start()
            ready_event.wait(timeout=5.0)

            try:
                while not stop_event.wait(0.1):
                    pass
            finally:
                client.loop_stop()
                client.disconnect()

        # Finalni commit nebo zahazeni cache resi hlavni vlakno, aby se
        # neulozil nedokonceny soubor po prerusenem replayi.

    thread = threading.Thread(target=runner, name="replay_frame_cache_thread", daemon=True)
    thread.start()
    ready_event.wait(timeout=5.0)
    return {
        "thread": thread,
        "stop_event": stop_event,
        "output_path": output_path,
        "temp_path": temp_path,
        "state": state,
    }


def stop_frame_cache_recorder(recorder: dict | None, commit: bool) -> None:
    if not recorder:
        return

    recorder["stop_event"].set()
    recorder["thread"].join(timeout=5.0)
    temp_path = recorder["temp_path"]
    output_path = recorder["output_path"]
    frames = recorder["state"]["frames"]

    if commit and frames > 0 and temp_path.exists():
        temp_path.replace(output_path)
        return

    if temp_path.exists():
        temp_path.unlink()


def hold_cache_server() -> None:
    print("Replay: frame cache je pripravena. Server bezi, ukonci ho Ctrl+C.", flush=True)
    while True:
        time.sleep(0.5)


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
    frame_cache_path = get_frame_cache_path(run_dir)
    preload_dataset_path = resolve_preload_dataset_path(run_dir)
    timeline_dataset_path = get_timeline_dataset_path(run_dir)

    if args.input_dir:
        print(f"Replay: pouzivam experiment {run_dir}", flush=True)
    else:
        print(f"Replay: --input-dir nebyl zadany, pouzivam preferovany experiment {run_dir}", flush=True)
    metadata = load_metadata(run_dir)

    run_id = str(metadata.get("run_id", run_dir.name)).strip()
    if run_id:
        active_run_id = set_current_run_id(run_id)
        print(f"Replay: aktivni run_id = {active_run_id}", flush=True)

    if args.use_frame_cache and args.rebuild_frame_cache:
        remove_timeline_cache(run_dir)

    if args.use_frame_cache and not args.rebuild_frame_cache:
        timeline_stale, stale_reason = is_timeline_cache_stale(run_dir, metadata, args)
        if timeline_stale:
            if stale_reason:
                print(f"Replay: timeline cache je zastarala ({stale_reason}), premazavam ji.", flush=True)
            remove_timeline_cache(run_dir)

    if args.use_frame_cache and not timeline_dataset_path.exists():
        try:
            built_timeline_path = build_replay_timeline_dataset(run_dir, metadata, args)
            if built_timeline_path:
                timeline_dataset_path = built_timeline_path
        except Exception as exc:
            print(f"Replay: timeline dataset se nepodarilo pripravit ({exc}). Pokracuji bez nej.", flush=True)

    use_existing_frame_cache = (
        args.use_frame_cache
        and not args.rebuild_frame_cache
        and preload_dataset_path is not None
    )

    if use_existing_frame_cache:
        web_app.configure_replay_frame_cache(preload_dataset_path)
        web_app.configure_replay_timeline_cache(timeline_dataset_path if timeline_dataset_path.exists() else None)
        preloaded_frames = count_ndjson_records(preload_dataset_path)
        expected_fused_frames = metadata.get("fused_messages")
        expected_suffix = (
            f", metadata fused_messages={expected_fused_frames}"
            if isinstance(expected_fused_frames, int)
            else ""
        )
        timeline_suffix = ""
        if timeline_dataset_path.exists():
            timeline_suffix = f", timeline={count_ndjson_records(timeline_dataset_path)}"
        print(
            f"Replay: nalezen preload dataset {preload_dataset_path} "
            f"({preloaded_frames} framu{expected_suffix}{timeline_suffix}).",
            flush=True,
        )
        if args.start_local_stack:
            args.api_port = find_available_tcp_port(args.api_host, args.api_port)
            print(f"Replay: startuji lokalni API na http://{args.api_host}:{args.api_port}", flush=True)
            start_api_thread(args.api_host, args.api_port)
            if args.startup_wait > 0:
                print(f"Replay: cekam {args.startup_wait:.1f}s na nabeh lokalniho API.", flush=True)
                time.sleep(args.startup_wait)
        else:
            print("Replay: frame cache je k dispozici, ale lokalni API start je vypnuty.", flush=True)
            return
        hold_cache_server()
        return

    web_app.configure_replay_frame_cache(None)
    web_app.configure_replay_timeline_cache(None)
    maybe_start_local_stack(args)

    print(f"Replay: nacitam raw zaznam z {raw_path}", flush=True)
    records = load_records(raw_path)
    if args.max_records > 0:
        records = records[: args.max_records]

    if args.with_optitrack_reference:
        print("Replay: startuji soubezne OptiTrack referenci do samostatneho dashboard modu.", flush=True)
        start_optitrack_reference_thread(args)

    recorder = start_frame_cache_recorder(args.host, args.port, frame_cache_path)
    client = mqtt.Client(client_id="four_raw_replay")
    client.connect(args.host, args.port)
    client.loop_start()

    print(f"Replay: nacteno {len(records)} raw zprav z {raw_path}", flush=True)
    print(f"Replay: host={args.host}:{args.port}, rate={args.rate}", flush=True)

    replay_completed = False
    try:
        iteration = 0
        while True:
            iteration += 1
            print(f"Replay: iterace {iteration} start.")
            replay_once(client, records, args.rate)
            print("Replay: iterace dokoncena.")
            if not args.loop:
                replay_completed = True
                break
    finally:
        client.loop_stop()
        client.disconnect()
        if replay_completed:
            print("Replay: cekam 0.8s na dopsani poslednich fused snimku do cache.", flush=True)
            time.sleep(0.8)
        stop_frame_cache_recorder(recorder, commit=replay_completed)

    cached_frames = recorder["state"]["frames"]
    if replay_completed and cached_frames > 0:
        print(
            f"Replay: ulozena frame cache {frame_cache_path} "
            f"({cached_frames} snimku). Pri dalsim spusteni se muze nacist najednou.",
            flush=True,
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nReplay stopped.")
