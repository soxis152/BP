"""Replay trajektorie z OptiTrack exportu do stavajici MQTT/DB pipeline.

Scenar necte radar ani BLE z fyzickych senzoru. Misto toho vezme ground truth
trajektorie z OptiTrack XLSX, prevede je do souradnic mistnosti a z nich
vygeneruje synteticka radarova + BLE mereni pres stejny helper jako ostatni
testovaci scenare.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import re
import time

import paho.mqtt.client as mqtt

try:
    from Four.config import BLE_CONFIGS, MQTT_HOST, MQTT_PORT, RADAR_CONFIGS, RUN_ID
    from Four.db_handler import db_handler
    from Four.test_soubory.optitrack_xlsx import (
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
        from test_soubory.optitrack_xlsx import compute_auto_fit_offsets, compute_bounds, load_optitrack_take, shift_take
        from test_soubory.scenario_common import (
            ObjectState,
            build_ble_records,
            build_radar_records,
            publish_and_store,
            update_object_velocities,
        )
    except ImportError:
        from .optitrack_xlsx import compute_auto_fit_offsets, compute_bounds, load_optitrack_take, shift_take
        from .scenario_common import (
            ObjectState,
            build_ble_records,
            build_radar_records,
            publish_and_store,
            update_object_velocities,
        )
        from ..config import BLE_CONFIGS, MQTT_HOST, MQTT_PORT, RADAR_CONFIGS, RUN_ID
        from ..db_handler import db_handler


DEFAULT_XLSX = Path(__file__).resolve().parents[1] / "data" / "optitrack" / "test_dronaren.xlsx"
DEFAULT_AXIS_X = "x"
DEFAULT_AXIS_Y = "-z"
DEFAULT_AXIS_Z = "y"


def sanitize_tag_id(name: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
    return cleaned or "OPTITRACK_OBJECT"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay OptiTrack XLSX trajektorie pres testovaci MQTT pipeline projektu Four."
    )
    parser.add_argument("--xlsx", default=str(DEFAULT_XLSX), help="Cesta k OptiTrack XLSX exportu.")
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
    parser.add_argument("--offset-x", type=float, default=0.0, help="Rucni posun X po prevodu os.")
    parser.add_argument("--offset-y", type=float, default=0.0, help="Rucni posun Y po prevodu os.")
    parser.add_argument("--offset-z", type=float, default=0.0, help="Rucni posun Z po prevodu os.")
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
    parser.add_argument("--frame-stride", type=int, default=1, help="Pouzit kazdy N-ty frame z XLSX.")
    parser.add_argument("--max-frames", type=int, default=0, help="Volitelne omezeni poctu prehranych framu.")
    parser.add_argument("--loop", action="store_true", help="Po dojeti znovu prehravat od zacatku.")
    return parser.parse_args()


def clone_object_states(take):
    initial_frame = next((frame for frame in take.frames if frame.bodies), None)
    if initial_frame is None:
        raise ValueError("OptiTrack take neobsahuje zadny frame s pozici rigid body.")

    objects = []
    for body in take.rigid_bodies:
        x, y, z = initial_frame.bodies.get(body.name, (0.0, 0.0, 0.0))
        objects.append(ObjectState(sanitize_tag_id(body.name), x=x, y=y, z=z))
    return objects


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
    print(f"- axis mapping: X={args.axis_x}, Y={args.axis_y}, Z={args.axis_z}")
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


async def run_replay(args: argparse.Namespace) -> None:
    manual_take = load_optitrack_take(
        args.xlsx,
        sheet_name=args.sheet,
        axis_x=args.axis_x,
        axis_y=args.axis_y,
        axis_z=args.axis_z,
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
    selected_frames = take.frames[::frame_step]
    if args.max_frames > 0:
        selected_frames = selected_frames[: args.max_frames]
    if not selected_frames:
        raise ValueError("Po aplikaci frame stride/max_frames nezustal zadny frame.")

    playback_period = max(0.001, take.frame_period_seconds * frame_step / max(args.speed, 0.001))

    mqtt_client = mqtt.Client(client_id="scenario_optitrack_replay")
    mqtt_client.connect(MQTT_HOST, MQTT_PORT)
    mqtt_client.loop_start()

    await db_handler.connect()
    await db_handler.init_tables()

    try:
        iteration = 0
        while True:
            iteration += 1
            print(f"OptiTrack replay: iterace {iteration} start ({len(selected_frames)} framu).")

            for take_frame in selected_frames:
                cycle_started = time.time()
                previous_positions = apply_frame_to_objects(objects, body_names_by_object_id, take_frame)

                update_object_velocities(objects, previous_positions, playback_period)

                for cfg in RADAR_CONFIGS:
                    records = build_radar_records(objects, cfg, cycle_started)
                    await publish_and_store(mqtt_client, cfg["id"], records, is_radar=True)

                for cfg in BLE_CONFIGS:
                    records = build_ble_records(objects, cfg, cycle_started)
                    await publish_and_store(mqtt_client, cfg["id"], records, is_radar=False)

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
