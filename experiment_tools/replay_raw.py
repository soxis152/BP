"""Replay raw MQTT zaznamu z predchoziho experimentu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import paho.mqtt.client as mqtt

try:
    from Four.config import MQTT_HOST, MQTT_PORT
except ImportError:
    try:
        from config import MQTT_HOST, MQTT_PORT
    except ImportError:
        from ..config import MQTT_HOST, MQTT_PORT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prehraje raw.ndjson zpet do MQTT.")
    parser.add_argument("--input-dir", required=True, help="Adresar experimentu s raw.ndjson.")
    parser.add_argument("--host", default=MQTT_HOST, help="MQTT host.")
    parser.add_argument("--port", type=int, default=MQTT_PORT, help="MQTT port.")
    parser.add_argument("--rate", type=float, default=1.0, help="Rychlost prehravani. 1.0 = realny cas.")
    parser.add_argument("--loop", action="store_true", help="Po dojeti zacit znovu od zacatku.")
    parser.add_argument("--max-records", type=int, default=0, help="Volitelne omezeni poctu prehranych zprav.")
    return parser.parse_args()


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


def main() -> None:
    args = parse_args()
    run_dir = Path(args.input_dir).resolve()
    raw_path = run_dir / "raw.ndjson"
    records = load_records(raw_path)
    if args.max_records > 0:
        records = records[: args.max_records]

    client = mqtt.Client(client_id="four_raw_replay")
    client.connect(args.host, args.port)
    client.loop_start()

    print(f"Replay: nacteno {len(records)} raw zprav z {raw_path}")
    print(f"Replay: host={args.host}:{args.port}, rate={args.rate}")

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
