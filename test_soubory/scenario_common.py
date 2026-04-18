import asyncio
import json
import math
import random
import time

import paho.mqtt.client as mqtt

from Four.db_handler import db_handler

# Tento modul je společná testovací infrastruktura pro všechny scénáře ve složce test_soubory.
#
# Jeho úloha:
# 1. držet "ground truth" stav simulovaných objektů,
# 2. z této ground truth generovat syntetická radarová a BLE měření,
# 3. publikovat tato měření do stejného MQTT rozhraní, které používá reálný systém,
# 4. současně je ukládat do databáze, aby se testy daly později analyzovat.
#
# Díky tomu testovací scénáře nepíší přímo radarové body ani BLE věty.
# Stačí jim definovat pohyb objektu v mapě a helper se postará o zbytek.

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883

# Publish period odpovídá periodě, s jakou se typicky očekává nový krok simulace i fusion.
PUBLISH_PERIOD_SECONDS = 0.15
MAX_SYNTHETIC_SPEED_MPS = 4.0

# Geometrie senzorů v testech musí odpovídat hlavnímu systému, jinak by testy netestovaly
# stejnou matematiku jako ostrý běh.
RADAR_CONFIGS = [
    {"id": "radar_1", "pos_x": 1.5, "pos_y": 0.0, "pos_z": 0.8, "rotation": 0},
    {"id": "radar_2", "pos_x": 0.0, "pos_y": 1.5, "pos_z": 0.8, "rotation": -90},
]

BLE_CONFIGS = [
    {"id": "ble_1", "pos_x": 1.5, "pos_y": 0.0, "pos_z": 0.8, "rotation": 90},
    {"id": "ble_2", "pos_x": 0.0, "pos_y": 1.5, "pos_z": 0.8, "rotation": 0},
]


class ObjectState:
    """Stav jednoho simulovaného objektu.

    Objekt reprezentuje ideální "pravdu" testu, tedy skutečnou polohu a případně rychlost.
    Z tohoto stavu se teprve odvozují syntetická radarová a BLE měření.

    Vedle polohy a rychlosti obsahuje i přepínače pro simulaci:
    - viditelnosti pro radar a BLE,
    - dodatečného šumu v jednotlivých senzorech.
    """

    def __init__(self, tag_id, x, y, z=0.92, vx=0.0, vy=0.0):
        self.tag_id = tag_id
        self.x = x
        self.y = y
        self.z = z
        self.vx = vx
        self.vy = vy

        # Přepínače viditelnosti umožňují simulovat zakrytí nebo úplný dropout senzoru.
        self.radar_visible = True
        self.ble_visible = True

        # Dodatečný šum slouží pro stress testy stability fusion logiky.
        self.radar_noise_xy = 0.0
        self.radar_noise_z = 0.0
        self.ble_azimuth_noise = 0.0
        self.ble_rssi_noise = 0.0


def transform_to_global(x_loc, y_loc, z_loc, cfg):
    """Převede lokální souřadnice senzoru do globální mapy místnosti."""
    angle_rad = math.radians(cfg["rotation"])
    x_glob = x_loc * math.cos(angle_rad) - y_loc * math.sin(angle_rad)
    y_glob = x_loc * math.sin(angle_rad) + y_loc * math.cos(angle_rad)
    return x_glob + cfg["pos_x"], y_glob + cfg["pos_y"], z_loc + cfg["pos_z"]


def transform_to_local(x_glob, y_glob, z_glob, cfg):
    """Převede globální souřadnice objektu do lokálního systému konkrétního senzoru."""
    dx = x_glob - cfg["pos_x"]
    dy = y_glob - cfg["pos_y"]
    dz = z_glob - cfg["pos_z"]
    angle_rad = math.radians(cfg["rotation"])
    x_loc = dx * math.cos(angle_rad) + dy * math.sin(angle_rad)
    y_loc = -dx * math.sin(angle_rad) + dy * math.cos(angle_rad)
    return x_loc, y_loc, dz


def normalize_angle(angle_deg):
    """Normalizuje úhel do intervalu <-180, 180> pro jednodušší práci s BLE azimutem."""
    return ((angle_deg + 180.0) % 360.0) - 180.0


def update_object_velocities(objects, previous_positions, dt):
    if dt <= 0.0:
        return

    for obj in objects:
        previous = previous_positions.get(id(obj))
        if previous is None:
            continue

        prev_x, prev_y = previous
        vx = (obj.x - prev_x) / dt
        vy = (obj.y - prev_y) / dt
        speed = math.hypot(vx, vy)

        if speed > MAX_SYNTHETIC_SPEED_MPS:
            obj.vx = 0.0
            obj.vy = 0.0
            continue

        obj.vx = vx
        obj.vy = vy


def estimate_radial_doppler(obj, cfg):
    dx = obj.x - cfg["pos_x"]
    dy = obj.y - cfg["pos_y"]
    distance_xy = math.hypot(dx, dy)
    if distance_xy <= 0.001:
        return 0.0

    return (obj.vx * dx + obj.vy * dy) / distance_xy


def build_radar_records(objects, cfg, timestamp):
    """Vygeneruje syntetické radarové body pro jeden radar.

    Princip:
    - každý objekt se převede do lokálního systému radaru,
    - zkontroluje se, zda je ve zorném poli,
    - kolem skutečné polohy se vytvoří malý shluk bodů,
    - každý bod dostane mírně odlišnou pozici a SNR.

    Tím vzniká realistická simulace radaru:
    radar nevidí ideální jediný bod, ale "mrak" odrazů kolem objektu.
    """
    records = []

    for obj in objects:
        if not obj.radar_visible:
            continue

        x_loc, y_loc, z_loc = transform_to_local(obj.x, obj.y, obj.z, cfg)
        distance = math.sqrt(x_loc**2 + y_loc**2 + z_loc**2)
        azimuth_local = math.degrees(math.atan2(y_loc, x_loc))

        # Jednoduchý model viditelnosti radaru:
        # - objekt musí být před radarem,
        # - musí být v maximálním dosahu,
        # - musí být v rozumném zorném poli.
        if x_loc <= 0.0 or distance > 5.0 or abs(azimuth_local) > 70.0:
            continue

        cluster_size = random.randint(3, 5)
        for _ in range(cluster_size):
            point_x_loc = x_loc + random.uniform(-0.12, 0.12) + random.gauss(0.0, obj.radar_noise_xy)
            point_y_loc = y_loc + random.uniform(-0.12, 0.12) + random.gauss(0.0, obj.radar_noise_xy)
            point_z_loc = z_loc + random.uniform(-0.04, 0.04) + random.gauss(0.0, obj.radar_noise_z)
            point_x_glob, point_y_glob, point_z_glob = transform_to_global(point_x_loc, point_y_loc, point_z_loc, cfg)

            # SNR zde není přesný fyzikální model, ale dostatečně realistická aproximace:
            # s rostoucí vzdáleností zpravidla klesá a zároveň lehce kolísá.
            snr = max(7.0, 23.0 - distance * 2.6 + random.uniform(-1.8, 1.8))
            doppler = estimate_radial_doppler(obj, cfg)

            records.append(
                (
                    timestamp,
                    round(point_x_glob, 3),
                    round(point_y_glob, 3),
                    round(point_z_glob, 3),
                    round(snr, 2),
                    round(doppler, 3),
                )
            )

    return records


def build_ble_records(objects, cfg, timestamp):
    """Vygeneruje syntetická BLE měření pro jednu kotvu.

    BLE kotva zde nevrací přesnou polohu objektu.
    Vrací:
    - identitu tagu,
    - RSSI,
    - azimut.

    Proto je BLE v testech vhodné hlavně jako zdroj identity
    a hrubého směrového omezení, nikoli jako přesný zdroj polohy.
    """
    records = []

    for obj in objects:
        if not obj.ble_visible:
            continue

        dx = obj.x - cfg["pos_x"]
        dy = obj.y - cfg["pos_y"]
        dz = obj.z - cfg["pos_z"]
        distance = math.sqrt(dx**2 + dy**2 + dz**2)
        world_angle = math.degrees(math.atan2(dy, dx))
        relative_azimuth = normalize_angle(world_angle - cfg["rotation"])

        # Jednoduchý model viditelnosti BLE kotvy.
        if distance > 8.0 or abs(relative_azimuth) > 85.0:
            continue

        cluster_size = random.randint(3, 5)
        expected_rssi = -45.0 - distance * 9.0
        for _ in range(cluster_size):
            azimuth = relative_azimuth + random.uniform(-3.5, 3.5) + random.gauss(0.0, obj.ble_azimuth_noise)
            rssi = int(round(expected_rssi + random.uniform(-2.0, 2.0) + random.gauss(0.0, obj.ble_rssi_noise)))
            records.append((timestamp, obj.tag_id, rssi, round(azimuth, 2)))

    return records


async def publish_and_store(mqtt_client, sensor_name, records, is_radar):
    """Publikuje syntetická měření do MQTT a zároveň je uloží do DB.

    Testovací scénáře tak používají úplně stejnou vstupní cestu jako reálné senzory:
    - fusion vrstva čte data z MQTT,
    - historie testu se ukládá do databáze.
    """
    for record in records:
        if is_radar:
            payload = {
                "timestamp": record[0],
                "x": record[1],
                "y": record[2],
                "z": record[3],
                "snr": record[4],
                "doppler": record[5],
            }
        else:
            payload = {
                "timestamp": record[0],
                "tag_id": record[1],
                "rssi": record[2],
                "azimuth": record[3],
            }

        mqtt_client.publish(f"sensors/raw/{sensor_name}", json.dumps(payload))

    if records:
        await db_handler.insert_batch(sensor_name, records)


async def run_scenario(scenario_name, objects, update_fn):
    """Spustí nekonečný testovací scénář.

    `update_fn` v každém kroku upraví "ground truth" objektů.
    Helper pak:
    1. zaktualizuje stav objektů,
    2. vygeneruje radarová a BLE měření,
    3. publikuje je do MQTT,
    4. uloží je do DB,
    5. počká do dalšího kroku.

    Díky tomu stačí jednotlivým testům definovat jen pohyb a případné dropout/noise podmínky.
    """
    mqtt_client = mqtt.Client(client_id=f"scenario_{scenario_name}")
    mqtt_client.connect(MQTT_HOST, MQTT_PORT)
    mqtt_client.loop_start()

    await db_handler.connect()
    await db_handler.init_tables()

    print(f"Running scenario: {scenario_name}. Stop with Ctrl+C.")
    step_index = 0

    try:
        while True:
            cycle_started = time.time()
            previous_positions = {id(obj): (obj.x, obj.y) for obj in objects}

            # update_fn je jediné místo, kde se mění ideální svět scénáře.
            update_fn(step_index, objects, PUBLISH_PERIOD_SECONDS)
            update_object_velocities(objects, previous_positions, PUBLISH_PERIOD_SECONDS)

            for cfg in RADAR_CONFIGS:
                records = build_radar_records(objects, cfg, cycle_started)
                await publish_and_store(mqtt_client, cfg["id"], records, is_radar=True)

            for cfg in BLE_CONFIGS:
                records = build_ble_records(objects, cfg, cycle_started)
                await publish_and_store(mqtt_client, cfg["id"], records, is_radar=False)

            step_index += 1
            elapsed = time.time() - cycle_started
            await asyncio.sleep(max(0.0, PUBLISH_PERIOD_SECONDS - elapsed))
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
