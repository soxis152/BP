#!/usr/bin/env python3
"""Jednoducha diagnostika radar CLI portu.

Pouziti:
    python scripts/test_radar_cli.py --cfg-port /dev/ttyACM0

Skript nacte radarovy profil, posle ho po jednotlivych prikazech na CLI port
a po kazdem prikazu vypise odpoved radaru. Zastavi se na prvni chybe, aby bylo
videt, jestli radar pada az na `sensorStart`, nebo uz na nekterem drivejsim
parametru profilu.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import serial


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from config import RADAR_CFG_BAUD, RADAR_CONFIG_FILE, RADAR_DATA_BAUD  # noqa: E402


CONTROL_COMMANDS = {"sensorStop", "flushCfg", "sensorStart"}
CONTROL_DELAY_SECONDS = 0.50
COMMAND_DELAY_SECONDS = 0.12
RESPONSE_TIMEOUT_SECONDS = 2.0
RESPONSE_POLL_SECONDS = 0.05


def load_radar_config_commands(config_path: Path) -> list[str]:
    commands: list[str] = []
    with config_path.open("r", encoding="utf-8", errors="ignore") as file_handle:
        for line in file_handle:
            command = line.strip()
            if not command or command.startswith("%") or command.startswith("configDataPort "):
                continue
            commands.append(command)
    config_data_port_command = f"configDataPort {RADAR_DATA_BAUD} 0"
    insert_index = None
    for index, command in enumerate(commands):
        if command.startswith("calibData "):
            insert_index = index
            break
    if insert_index is None:
        for index, command in enumerate(commands):
            if command == "sensorStart":
                insert_index = index
                break
    if insert_index is not None:
        commands.insert(insert_index, config_data_port_command)
    else:
        commands.append(config_data_port_command)
    return commands


def read_radar_command_response(serial_handle: serial.Serial) -> list[str]:
    response: list[str] = []
    deadline = time.monotonic() + RESPONSE_TIMEOUT_SECONDS

    while time.monotonic() < deadline:
        if serial_handle.in_waiting <= 0:
            time.sleep(RESPONSE_POLL_SECONDS)
            continue

        raw_line = serial_handle.readline()
        if not raw_line:
            continue

        line = raw_line.decode(errors="ignore").strip()
        if not line:
            continue

        response.append(line)
        if "Done" in line or "Error" in line or "mmwDemo:/>" in line:
            break

    return response


def sync_radar_cli(serial_handle: serial.Serial) -> None:
    serial_handle.reset_input_buffer()
    serial_handle.reset_output_buffer()
    serial_handle.write(b"\n")
    serial_handle.flush()
    time.sleep(CONTROL_DELAY_SECONDS)
    read_radar_command_response(serial_handle)


def run_cli_diagnostic(cfg_port: str, baudrate: int, config_path: Path) -> int:
    commands = load_radar_config_commands(config_path)
    print(f"CLI port: {cfg_port}")
    print(f"Baudrate: {baudrate}")
    print(f"Config:   {config_path}")
    print(f"Commands: {len(commands)}")
    print()

    with serial.Serial(cfg_port, baudrate, timeout=1) as serial_handle:
        sync_radar_cli(serial_handle)

        for index, command in enumerate(commands, start=1):
            print(f"[{index:02d}/{len(commands):02d}] >>> {command}")
            serial_handle.reset_input_buffer()
            serial_handle.write((command + "\n").encode("ascii"))
            serial_handle.flush()

            delay = CONTROL_DELAY_SECONDS if command in CONTROL_COMMANDS else COMMAND_DELAY_SECONDS
            time.sleep(delay)

            response = read_radar_command_response(serial_handle)
            if response:
                for line in response:
                    print(f"         {line}")
            else:
                print("         <no response>")

            has_done = any("Done" in line for line in response)
            has_prompt = any("mmwDemo:/>" in line for line in response)
            has_error = any("Error" in line or "not recognized as a CLI command" in line for line in response)
            if not has_done and (has_error or not has_prompt):
                print()
                print(f"FAILED on command: {command}")
                return 1

            print()

    print("Radar CLI configuration finished without detected command failure.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Step-by-step radar CLI diagnostic")
    parser.add_argument("--cfg-port", required=True, help="Radar CLI/config port, e.g. /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=RADAR_CFG_BAUD, help=f"CLI baudrate (default: {RADAR_CFG_BAUD})")
    parser.add_argument(
        "--config",
        type=Path,
        default=RADAR_CONFIG_FILE,
        help=f"Radar profile path (default: {RADAR_CONFIG_FILE})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_cli_diagnostic(args.cfg_port, args.baud, args.config.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
