"""Samostatna utilita pro rucni test jednoho radaru.

Tento soubor neni hlavni cesta produkcniho behu. Hlavni system pouziva
`ingestion.py`, kde se spousti dva radary, BLE kotvy, MQTT a DB zapis.

`rad.py` je uzitecny hlavne pri ozivovani hardwaru: vybere nebo pouzije pevne
COM porty, posle konfiguraci do radaru a zobrazi body v jednoduchem matplotlib
okne. Proto je kod vice interaktivni a mene obecny nez ingestion worker.
"""

import json
import os
import re
import threading
import time
from collections import defaultdict, deque

import serial
import serial.tools.list_ports
from radar_interface import RadarInterface
from radar_ui import RadarUI


RADAR_CONFIG = r"C:\Users\kabup\OneDrive\Plocha\BP_\KÓD\BLE + RADAR\radar\tdm\AWR294X_profile_2025_11_07T16_27_59_226 copy2.cfg"

BAUD_RATE_CON = 115200
BAUD_RATE_DAT = 921600

con_timeout = 0.01
dat_timeout = 1

configDataPort = f"configDataPort {BAUD_RATE_DAT} 0"


def parse_cfg_file(file_path):
    """
    Parses a radar configuration (.cfg) file and returns an array of commands.
    Comment lines (starting with '%') are ignored.

    :param file_path: Path to the .cfg file.
    :return: List of configuration commands (strings).
    """
    commands = []
    try:
        with open(file_path, 'r') as file:
            for line in file:
                stripped_line = line.strip()
                if stripped_line and not stripped_line.startswith('%'):
                    commands.append(stripped_line)
        return commands
    except FileNotFoundError:
        print(f"Error: File not found at {file_path}")
        return []
    except Exception as e:
        print(f"Error: An error occurred while reading the file - {e}")
        return []


def configure(port):
    # Konfigurace se posila po radcich stejne, jako kdyby se profil zadaval
    # rucne pres terminal. Radar po uspesnem prikazu typicky vraci "Done".
    with serial.Serial(port, BAUD_RATE_CON, timeout=con_timeout) as ser:
        ser.reset_input_buffer()  # Flush input buffer
        try:
            config_commands = parse_cfg_file(RADAR_CONFIG)
            if len(config_commands) == 0:
                return

            config_commands.insert(-2, configDataPort)

            for cmd in config_commands:
                ser.write((cmd + "\n").encode())

                if cmd == "sensorStop" or cmd == "sensorStart":
                    time.sleep(0.1)

                response = ser.readlines()
                response = [line.decode().strip() for line in response]

                if len(response) >= 2 and response[-2] == "Done":
                    print(".", end="", flush=True)
                else:
                    raise Exception(f"Failed to execute {cmd}\nresponse: {response}")

            print("\nConfiguration commands sent successfully.")
        except serial.SerialException as e:
            print(f"Error opening serial port: {e}")
        finally:
            if ser.is_open:
                ser.close()
            print("Serial port closed.")


def select_two_ports():
    # Interaktivni vyber se hodi pri prvnim zapojeni radaru, kdy jeste neni
    # jasne, ktere COM cislo Windows zarizeni pridelil.
    ports = [port.device for port in serial.tools.list_ports.comports()]
    if len(ports) < 2:
        print("Not enough COM ports found.")
        return None
    print("Available COM ports:")
    for i, port in enumerate(ports):
        print(f"{i}: {port}")
    selected_ports = []
    for selection_num in range(2):
        while True:
            try:
                selection = int(input(f"Select port {selection_num + 1}: "))
                if 0 <= selection < len(ports) and ports[selection] not in selected_ports:
                    selected_ports.append(ports[selection])
                    print(f"Selected port {selection_num + 1}: {ports[selection]}")
                    break
                elif ports[selection] in selected_ports:
                    print("You've already selected this port. Choose a different one.")
                else:
                    print("Invalid selection.")
            except ValueError:
                print("Enter a valid number.")
    return selected_ports


def load_or_select_ports():
    """
    Directly returns the fixed ports COM19 (config) and COM18 (data).
    :return: A list of two fixed ports.
    """
    # Hardcoded ports. Pro rychle laboratorni testy je pohodlnejsi mit pevne
    # hodnoty, ale v hlavnim systemu jsou porty soustredene v `ingestion.py`.
    config_port = "COM11"
    data_port = "COM12"

    # Validate the ports
    try:
        with serial.Serial(config_port, BAUD_RATE_CON, timeout=con_timeout):
            pass
        with serial.Serial(data_port, BAUD_RATE_DAT, timeout=dat_timeout):
            pass
        print(f"Using fixed ports: CONFIG={config_port}, DATA={data_port}")
        return [config_port, data_port]
    except serial.SerialException as e:
        print(f"Error: Unable to access the ports COM19 and COM18. Details: {e}")
        exit(1)  # Exit if the fixed ports are not accessible


def main():
    # Minimalni smycka: nakonfigurovat radar, cist binarni data, parsovat frame
    # a poslat vysledek do jednoduche 3D vizualizace.
    selected_ports = load_or_select_ports()
    if selected_ports and len(selected_ports) == 2:
        port1, port2 = selected_ports
        print(f"Using CONSOLE port: {port1} and DATA port: {port2}")
        configure(port1)

        print("Reading data")
        radar = RadarInterface(port=port2, baudrate=BAUD_RATE_DAT)
        radarUI = RadarUI(2, 2)
        try:
            while True:
                raw_data = radar.read_data()
                if raw_data:
                    parsed_results = radar.parse_frame(raw_data)
                    radarUI.update(parsed_results)
        except KeyboardInterrupt:
            print("Exiting...")
        finally:
            radar.close()


if __name__ == "__main__":
    main()
