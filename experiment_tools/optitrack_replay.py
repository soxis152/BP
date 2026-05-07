"""Replay trajektorie z OptiTrack exportu do dashboardu nebo testovaci pipeline.

Vychozi rezim `direct` bere OptiTrack jen jako referencni trajektorii a publikuje
ji jako samostatny stream pro dashboard. Volitelny rezim `via_fusion` zustava
jen pro starsi testovaci scenare, kde se z ground truth generoval synteticky
radar/BLE vstup.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re
import threading
import time

import paho.mqtt.client as mqtt
import uvicorn

try:
    from Four.config import BLE_CONFIGS, MQTT_HOST, MQTT_PORT, RADAR_CONFIGS, RUN_ID
    from Four.db_handler import db_handler
    from Four import app as web_app
    from Four import fusion
    from Four.experiment_tools.optitrack_xlsx import (
        compute_auto_fit_offsets,
        compute_bounds,
        load_optitrack_take,
        shift_take,
    )
    from Four.test_soubory.scenario_common import (
        ObjectState,
        build_ble_records,
        build_radar_records,
        publish_and_store,
        update_object_velocities,
    )
except ImportError:
    try:
        from config import BLE_CONFIGS, MQTT_HOST, MQTT_PORT, RADAR_CONFIGS, RUN_ID
        from db_handler import db_handler
        import app as web_app
        import fusion
        from experiment_tools.optitrack_xlsx import (
            compute_auto_fit_offsets,
            compute_bounds,
            load_optitrack_take,
            shift_take,
        )
        from test_soubory.scenario_common import (
            ObjectState,
            build_ble_records,
            build_radar_records,
            publish_and_store,
            update_object_velocities,
        )
    except ImportError:
        from Four.experiment_tools.optitrack_xlsx import compute_auto_fit_offsets, compute_bounds, load_optitrack_take, shift_take
        from Four.test_soubory.scenario_common import (
            ObjectState,
            build_ble_records,
            build_radar_records,
            publish_and_store,
            update_object_velocities,
        )
        from Four.config import BLE_CONFIGS, MQTT_HOST, MQTT_PORT, RADAR_CONFIGS, RUN_ID
        from Four.db_handler import db_handler
        from Four import app as web_app
        from Four import fusion


def resolve_default_input_path() -> Path:
    data_dir = Path(__file__).resolve().parents[1] / "data" / "optitrack"
    preferred = data_dir / "test_dronaren.xlsx"
    if preferred.exists():
        return preferred

    candidates = sorted(
        path for path in data_dir.glob("*")
        if path.is_file() and path.suffix.lower() in {".xlsx", ".csv"}
    )
    if candidates:
        return candidates[0]
    return preferred


DEFAULT_XLSX = resolve_default_input_path()
DEFAULT_AXIS_X = "-x"
DEFAULT_AXIS_Y = "z"
DEFAULT_AXIS_Z = "y"
DEFAULT_YAW_DEG = -89.4461
DEFAULT_OFFSET_X = 2.6268
DEFAULT_OFFSET_Y = 3.8304
DEFAULT_OFFSET_Z = -0.1569
DEFAULT_START_ON_BODY = "Phantom4"
OPTITRACK_REFERENCE_TOPIC = "sensors/reference/optitrack"


def sanitize_tag_id(name: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
    return cleaned or "OPTITRACK_OBJECT"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay OptiTrack XLSX/CSV trajektorie pres testovaci MQTT pipeline projektu Four."
    )
    parser.add_argument(
        "--input",
        "--xlsx",
        dest="input_path",
        default=str(DEFAULT_XLSX),
        help="Cesta k OptiTrack exportu (.xlsx nebo .csv).",
    )
    parser.add_argument("--sheet", default=None, help="Nazev sheetu. Vychozi je prvni sheet v souboru.")
    parser.add_argument(
        "--objects",
        nargs="+",
        default=None,
        help="Volitelny seznam rigid body jmen, ktere se maji prehrat. Vychozi je vse.",
    )
    parser.add_argument("--axis-x", default=DEFAULT_AXIS_X, help="Mapovani OptiTrack osy na systemovou X.")
    parser.add_argument("--axis-y", default=DEFAULT_AXIS_Y, help="Mapovani OptiTrack osy na systemovou Y.")
    parser.add_argument("--axis-z", default=DEFAULT_AXIS_Z, help="Mapovani OptiTrack osy na systemovou Z.")
    parser.add_argument("--yaw-deg", type=float, default=DEFAULT_YAW_DEG, help="Dodatecna rotace v rovine XY po mapovani os.")
    parser.add_argument("--offset-x", type=float, default=DEFAULT_OFFSET_X, help="Rucni posun X po prevodu os.")
    parser.add_argument("--offset-y", type=float, default=DEFAULT_OFFSET_Y, help="Rucni posun Y po prevodu os.")
    parser.add_argument("--offset-z", type=float, default=DEFAULT_OFFSET_Z, help="Rucni posun Z po prevodu os.")
    parser.add_argument(
        "--auto-fit-room",
        action="store_true",
        help="Automaticky vycentruje trajektorii do aktualni 3x3m mistnosti a zvedne ji nad podlahu.",
    )
    parser.add_argument("--room-size-x", type=float, default=3.0, help="Sirka mistnosti pro auto-fit.")
    parser.add_argument("--room-size-y", type=float, default=3.0, help="Hloubka mistnosti pro auto-fit.")
    parser.add_argument("--room-margin", type=float, default=0.35, help="Okraj mistnosti pro auto-fit.")
    parser.add_argument("--floor-z", type=float, default=0.15, help="Minimalni vyska Z po auto-fit.")
    parser.add_argument("--speed", type=float, default=1.0, help="Rychlost prehravani. 1.0 = realny cas.")
    parser.add_argument(
        "--initial-delay-sec",
        type=float,
        default=0.0,
        help="Kolik sekund cekat pred prvnim frame replaye. Hodi se pro casove srovnani s jinym streamem.",
    )
    parser.add_argument("--frame-stride", type=int, default=1, help="Pouzit kazdy N-ty frame z XLSX.")
    parser.add_argument("--max-frames", type=int, default=0, help="Volitelne omezeni poctu prehranych framu.")
    parser.add_argument("--loop", action="store_true", help="Po dojeti znovu prehravat od zacatku.")
    parser.add_argument(
        "--publish-mode",
        choices=("direct", "via_fusion"),
        default="direct",
        help="direct = poslat OptiTrack jako samostatnou dashboard referenci; via_fusion = vygenerovat synteticky radar/BLE vstup.",
    )
    parser.add_argument(
        "--start-on-body",
        default=DEFAULT_START_ON_BODY,
        help="Volitelne zacne replay az od prvniho framu, kde je videt dany rigid body (napr. Phantom4).",
    )
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
    return parser.parse_args()


def clone_object_states(take):
    first_positions_by_body = {}
    for frame in take.frames:
        for body in take.rigid_bodies:
            if body.name in first_positions_by_body:
                continue
            position = frame.bodies.get(body.name)
            if position is not None:
                first_positions_by_body[body.name] = position
        if len(first_positions_by_body) == len(take.rigid_bodies):
            break

    if not first_positions_by_body:
        raise ValueError("OptiTrack take neobsahuje zadny frame s pozici rigid body.")

    missing = [body.name for body in take.rigid_bodies if body.name not in first_positions_by_body]
    if missing:
        raise ValueError(
            "Pro nektere rigid body chybi viditelna pozice v celem take: "
            + ", ".join(missing)
        )

    objects = []
    for body in take.rigid_bodies:
        x, y, z = first_positions_by_body[body.name]
        obj = ObjectState(sanitize_tag_id(body.name), x=x, y=y, z=z)
        obj.radar_visible = False
        obj.ble_visible = False
        objects.append(obj)
    return objects


def trim_leading_frames(frames, start_on_body=None):
    if start_on_body:
        first_visible_index = next(
            (index for index, frame in enumerate(frames) if start_on_body in frame.bodies),
            None,
        )
        if first_visible_index is None:
            raise ValueError(
                f"Rigid body '{start_on_body}' nema v OptiTrack exportu zadny viditelny frame."
            )
        return frames[first_visible_index:]

    first_visible_index = next((index for index, frame in enumerate(frames) if frame.bodies), None)
    if first_visible_index is None:
        raise ValueError("OptiTrack take neobsahuje zadny frame s pozici rigid body.")
    return frames[first_visible_index:]


def print_take_summary(take, *, auto_fit_offsets, args):
    bounds = compute_bounds(take.frames)
    span_x = bounds["x"][1] - bounds["x"][0]
    span_y = bounds["y"][1] - bounds["y"][0]
    body_names = ", ".join(body.name for body in take.rigid_bodies)
    print("OptiTrack replay pripraven:")
    print(f"- soubor: {take.path}")
    print(f"- sheet: {take.sheet_name}")
    print(f"- rigid bodies: {body_names}")
    print(f"- framy: {len(take.frames)}")
    print(f"- export fps: {take.export_frame_rate or 'n/a'}")
    print(f"- capture fps: {take.capture_frame_rate or 'n/a'}")
    print(f"- playback stride: {args.frame_stride}")
    print(f"- playback speed: {args.speed}")
    print(f"- initial delay: {args.initial_delay_sec:.3f}s")
    print(f"- publish mode: {args.publish_mode}")
    if args.start_on_body:
        print(f"- replay start body: {args.start_on_body}")
    print(f"- axis mapping: X={args.axis_x}, Y={args.axis_y}, Z={args.axis_z}")
    print(f"- yaw rotation: {args.yaw_deg:.3f} deg")
    print(
        "- manual offset: "
        f"({args.offset_x:.3f}, {args.offset_y:.3f}, {args.offset_z:.3f}) m"
    )
    print(
        "- auto-fit offset: "
        f"({auto_fit_offsets[0]:.3f}, {auto_fit_offsets[1]:.3f}, {auto_fit_offsets[2]:.3f}) m"
    )
    print(
        "- bounds po prevodu: "
        f"x=<{bounds['x'][0]:.3f}, {bounds['x'][1]:.3f}> "
        f"y=<{bounds['y'][0]:.3f}, {bounds['y'][1]:.3f}> "
        f"z=<{bounds['z'][0]:.3f}, {bounds['z'][1]:.3f}> m"
    )
    if args.auto_fit_room and (span_x > args.room_size_x or span_y > args.room_size_y):
        print(
            "- warning: trajektorie se nevejde do zadaneho room-size ani po auto-fit; "
            "zvaz zvetseni --room-size-x/--room-size-y nebo upravu konfigurace senzoru."
        )
    print(f"- run_id: {RUN_ID}")
    print(f"- BLE anchors: {', '.join(cfg['id'] for cfg in BLE_CONFIGS)}")
    print(f"- radars: {', '.join(cfg['id'] for cfg in RADAR_CONFIGS)}")


def apply_frame_to_objects(objects, body_names_by_object_id, take_frame):
    previous_positions = {id(obj): (obj.x, obj.y) for obj in objects}
    visible_names = set(take_frame.bodies.keys())

    for obj in objects:
        source_name = body_names_by_object_id[id(obj)]
        if source_name not in visible_names:
            obj.radar_visible = False
            obj.ble_visible = False
            continue

        x, y, z = take_frame.bodies[source_name]
        obj.x = x
        obj.y = y
        obj.z = z
        obj.radar_visible = True
        obj.ble_visible = True

    return previous_positions


def start_fusion_thread() -> threading.Thread:
    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(fusion.main_fusion())
        finally:
            loop.close()

    thread = threading.Thread(target=runner, name="optitrack_replay_fusion_thread", daemon=True)
    thread.start()
    return thread


def start_api_thread(host: str, port: int) -> threading.Thread:
    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        config = uvicorn.Config(web_app.app, host=host, port=port, reload=False, loop="asyncio")
        server = uvicorn.Server(config)
        loop.run_until_complete(server.serve())

    thread = threading.Thread(target=runner, name="optitrack_replay_api_thread", daemon=True)
    thread.start()
    return thread


def maybe_start_local_stack(args: argparse.Namespace) -> None:
    if not args.start_local_stack:
        return

    if args.publish_mode == "via_fusion":
        print("OptiTrack replay: startuji lokalni fusion vrstvu.")
        start_fusion_thread()
    print(f"OptiTrack replay: startuji lokalni API na http://{args.api_host}:{args.api_port}")
    start_api_thread(args.api_host, args.api_port)

    if args.startup_wait > 0:
        print(f"OptiTrack replay: cekam {args.startup_wait:.1f}s na nabeh lokalniho stacku.")
        time.sleep(args.startup_wait)


async def run_replay(args: argparse.Namespace) -> None:
    maybe_start_local_stack(args)

    manual_take = load_optitrack_take(
        args.input_path,
        sheet_name=args.sheet,
        axis_x=args.axis_x,
        axis_y=args.axis_y,
        axis_z=args.axis_z,
        yaw_degrees=args.yaw_deg,
        offset_x=args.offset_x,
        offset_y=args.offset_y,
        offset_z=args.offset_z,
        selected_bodies=args.objects,
    )

    auto_fit_offsets = (0.0, 0.0, 0.0)
    take = manual_take
    if args.auto_fit_room:
        auto_fit_offsets = compute_auto_fit_offsets(
            manual_take.frames,
            room_size_x=args.room_size_x,
            room_size_y=args.room_size_y,
            room_margin=args.room_margin,
            floor_z=args.floor_z,
        )
        take = shift_take(
            manual_take,
            auto_fit_offsets[0],
            auto_fit_offsets[1],
            auto_fit_offsets[2],
        )

    print_take_summary(take, auto_fit_offsets=auto_fit_offsets, args=args)

    objects = clone_object_states(take)
    body_names_by_object_id = {
        id(obj): body.name for obj, body in zip(objects, take.rigid_bodies)
    }

    frame_step = max(1, args.frame_stride)
    selected_frames = trim_leading_frames(take.frames, start_on_body=args.start_on_body)[::frame_step]
    if args.max_frames > 0:
        selected_frames = selected_frames[: args.max_frames]
    if not selected_frames:
        raise ValueError("Po aplikaci frame stride/max_frames nezustal zadny frame.")

    playback_period = max(0.001, take.frame_period_seconds * frame_step / max(args.speed, 0.001))

    mqtt_client = mqtt.Client(client_id="scenario_optitrack_replay")
    mqtt_client.connect(MQTT_HOST, MQTT_PORT)
    mqtt_client.loop_start()

    if args.publish_mode == "via_fusion":
        await db_handler.connect()
        await db_handler.init_tables()

    try:
        iteration = 0
        while True:
            iteration += 1
            print(f"OptiTrack replay: iterace {iteration} start ({len(selected_frames)} framu).")

            if args.initial_delay_sec > 0:
                print(f"OptiTrack replay: cekam {args.initial_delay_sec:.3f}s pred prvnim framem.")
                await asyncio.sleep(args.initial_delay_sec)

            for take_frame in selected_frames:
                cycle_started = time.time()
                previous_positions = apply_frame_to_objects(objects, body_names_by_object_id, take_frame)

                update_object_velocities(objects, previous_positions, playback_period)

                if args.publish_mode == "via_fusion":
                    for cfg in RADAR_CONFIGS:
                        records = build_radar_records(objects, cfg, cycle_started)
                        await publish_and_store(mqtt_client, cfg["id"], records, is_radar=True)

                    for cfg in BLE_CONFIGS:
                        records = build_ble_records(objects, cfg, cycle_started)
                        await publish_and_store(mqtt_client, cfg["id"], records, is_radar=False)
                else:
                    visible_objects = []
                    for obj in objects:
                        if not (obj.radar_visible or obj.ble_visible):
                            continue
                        visible_objects.append(
                            {
                                "tag_id": obj.tag_id,
                                "object_type": "optitrack",
                                "source": "optitrack",
                                "x": round(obj.x, 4),
                                "y": round(obj.y, 4),
                                "z": round(obj.z, 4),
                                "confidence": 0.99,
                            }
                        )

                    payload = {
                        "source": "optitrack_reference",
                        "objects": visible_objects,
                        "stats": {
                            "timestamp": cycle_started,
                            "objects": len(visible_objects),
                            "optitrack_objects": len(visible_objects),
                            "stream_label": "OptiTrack reference",
                        },
                    }
                    mqtt_client.publish(OPTITRACK_REFERENCE_TOPIC, json.dumps(payload))

                elapsed = time.time() - cycle_started
                await asyncio.sleep(max(0.0, playback_period - elapsed))

            print("OptiTrack replay: konec zaznamu.")
            if not args.loop:
                break
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


async def main() -> None:
    args = parse_args()
    await run_replay(args)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nOptiTrack replay stopped.")
