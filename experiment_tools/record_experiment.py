"""Zaznam MQTT experimentu do lokalnich NDJSON souboru."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import time

import aiomqtt

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

try:
    from Four.config import BASE_DIR, DEFAULT_EXPERIMENT_LABEL, MQTT_HOST, MQTT_PORT
    from Four.run_context import set_current_run_id
except ImportError:
    try:
        from config import BASE_DIR, DEFAULT_EXPERIMENT_LABEL, MQTT_HOST, MQTT_PORT
        from run_context import set_current_run_id
    except ImportError:
        from ..config import BASE_DIR, DEFAULT_EXPERIMENT_LABEL, MQTT_HOST, MQTT_PORT
        from ..run_context import set_current_run_id


DEFAULT_OUTPUT_DIR = BASE_DIR / "runs" / "experiment"
DEFAULT_TOPICS = ("sensors/raw/#", "sensors/fused")


def sanitize_label(label: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", label.strip()).strip("_")
    return text or "experiment"


def build_run_dir(base_dir: Path, label: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = base_dir / f"{timestamp}_{sanitize_label(label)}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Nahraje MQTT provoz experimentu do souboru.")
    parser.add_argument(
        "--label",
        default=DEFAULT_EXPERIMENT_LABEL,
        help="Popisek experimentu pro jmeno slozky a zaroven aktivni run_id.",
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Adresar pro ulozeni experimentu.")
    parser.add_argument("--host", default=MQTT_HOST, help="MQTT host.")
    parser.add_argument("--port", type=int, default=MQTT_PORT, help="MQTT port.")
    parser.add_argument("--duration", type=float, default=0.0, help="Delka zaznamu v sekundach. 0 = az do Ctrl+C.")
    parser.add_argument("--note", default="", help="Volitelna poznamka k experimentu.")
    parser.add_argument("--topics", nargs="+", default=list(DEFAULT_TOPICS), help="Seznam MQTT topic filtru.")
    return parser.parse_args()


def extract_payload_timestamp(payload_text: str):
    try:
        data = json.loads(payload_text)
    except json.JSONDecodeError:
        return None

    if isinstance(data, dict):
        if "timestamp" in data:
            return data["timestamp"]
        stats = data.get("stats")
        if isinstance(stats, dict) and "timestamp" in stats:
            return stats["timestamp"]
    return None


async def record_messages(args: argparse.Namespace) -> Path:
    active_run_id = set_current_run_id(args.label)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = build_run_dir(output_dir, args.label)

    raw_path = run_dir / "raw.ndjson"
    fused_path = run_dir / "fused.ndjson"
    metadata_path = run_dir / "metadata.json"

    started_at = time.time()
    counts = {"raw": 0, "fused": 0}
    metadata = {
        "label": args.label,
        "run_id": active_run_id,
        "note": args.note,
        "mqtt_host": args.host,
        "mqtt_port": args.port,
        "topics": list(args.topics),
        "started_at": started_at,
        "started_at_iso": datetime.fromtimestamp(started_at).isoformat(),
        "raw_file": raw_path.name,
        "fused_file": fused_path.name,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Recorder: ukladam experiment do {run_dir}")
    print(f"Recorder: aktivni run_id = {active_run_id}")
    print(f"Recorder: topics = {', '.join(args.topics)}")

    try:
        async with aiomqtt.Client(args.host, args.port) as client:
            for topic in args.topics:
                await client.subscribe(topic)

            message_iterator = client.messages.__aiter__()
            started_monotonic = time.monotonic()

            with raw_path.open("w", encoding="utf-8") as raw_file, fused_path.open("w", encoding="utf-8") as fused_file:
                while True:
                    if args.duration > 0:
                        elapsed = time.monotonic() - started_monotonic
                        if elapsed >= args.duration:
                            break
                        timeout_seconds = min(1.0, args.duration - elapsed)
                    else:
                        timeout_seconds = 1.0

                    try:
                        async with asyncio.timeout(timeout_seconds):
                            message = await message_iterator.__anext__()
                    except TimeoutError:
                        continue

                    recorded_at = time.time()
                    topic = str(message.topic)
                    payload_text = message.payload.decode("utf-8", errors="replace")
                    record = {
                        "recorded_at": recorded_at,
                        "topic": topic,
                        "payload_text": payload_text,
                        "payload_timestamp": extract_payload_timestamp(payload_text),
                    }
                    line = json.dumps(record, ensure_ascii=False) + "\n"

                    if topic.startswith("sensors/raw/"):
                        raw_file.write(line)
                        counts["raw"] += 1
                        if counts["raw"] % 100 == 0:
                            raw_file.flush()
                    else:
                        fused_file.write(line)
                        counts["fused"] += 1
                        if counts["fused"] % 20 == 0:
                            fused_file.flush()
    finally:
        ended_at = time.time()
        metadata.update(
            {
                "ended_at": ended_at,
                "ended_at_iso": datetime.fromtimestamp(ended_at).isoformat(),
                "duration_seconds": ended_at - started_at,
                "raw_messages": counts["raw"],
                "fused_messages": counts["fused"],
            }
        )
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Recorder: hotovo. raw={counts['raw']} fused={counts['fused']}")
    return run_dir


async def main() -> None:
    args = parse_args()
    await record_messages(args)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nRecorder stopped.")
