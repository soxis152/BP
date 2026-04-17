import asyncio
import json
import math
import time

import aiomqtt

RAW_RADAR_HISTORY_SECONDS = 3.0
MAX_RAW_RADAR_HISTORY_POINTS = 700

# --- GEOMETRIE DLE INGESTION.PY ---
SENSORS = {
    "ble_1": {"x": 1.5, "y": 0.0, "facing_angle": 90},  # Na spodní zdi, kouká nahoru (+Y)
    "ble_2": {"x": 0.0, "y": 1.5, "facing_angle": 0},  # Na levé zdi, kouká doprava (+X)
}

# --- SDÍLENÁ DATA ---
shared_state = {
    "radar_points": [],
    "ble_tags": {"ble_1": {}, "ble_2": {}}
}
lock = asyncio.Lock()


def triangulate(tag_id):
    """Základní 2D průsečík dvou přímek z BLE."""
    b1 = shared_state["ble_tags"]["ble_1"].get(tag_id)
    b2 = shared_state["ble_tags"]["ble_2"].get(tag_id)

    if not b1 or not b2: return None

    # Převod u-blox azimutu na úhel v místnosti (0° je vpravo, 90° je nahoru)
    # Předpoklad: u-blox azimut kladný doprava, záporný doleva
    ang1 = math.radians(SENSORS["ble_1"]["facing_angle"] - b1["azimuth"])
    ang2 = math.radians(SENSORS["ble_2"]["facing_angle"] - b2["azimuth"])

    x1, y1 = SENSORS["ble_1"]["x"], SENSORS["ble_1"]["y"]
    x2, y2 = SENSORS["ble_2"]["x"], SENSORS["ble_2"]["y"]

    # Výpočet směrových vektorů
    v1x, v1y = math.cos(ang1), math.sin(ang1)
    v2x, v2y = math.cos(ang2), math.sin(ang2)

    # Průsečík (Cramerovo pravidlo)
    det = v1x * v2y - v1y * v2x
    if abs(det) < 0.001: return None  # Přímky jsou rovnoběžné

    dx = x2 - x1
    dy = y2 - y1
    t1 = (dx * v2y - dy * v2x) / det

    if t1 < 0: return None  # Průsečík je "za" senzorem

    x = x1 + t1 * v1x
    y = y1 + t1 * v1y

    # Omezení na velikost místnosti (3x3m s lehkým přesahem)
    if -0.5 <= x <= 3.5 and -0.5 <= y <= 3.5:
        return (x, y)
    return None


async def mqtt_listener():
    """Naslouchá datům z ingestion.py."""
    print("Fusion: Čekám na MQTT data na 'sensors/raw/#'...")
    async with aiomqtt.Client("127.0.0.1") as client:
        await client.subscribe("sensors/raw/#")
        async for message in client.messages:
            try:
                topic = str(message.topic)
                data = json.loads(message.payload.decode())

                async with lock:
                    if "radar" in topic:
                        # Ingestion.py už udělalo převod na globální x, y!
                        shared_state["radar_points"].append(data)
                    elif "ble_1" in topic:
                        shared_state["ble_tags"]["ble_1"][data["tag_id"]] = data
                    elif "ble_2" in topic:
                        shared_state["ble_tags"]["ble_2"][data["tag_id"]] = data
            except Exception:
                pass


async def fused_publisher():
    """Publikuje snapshot pro app.py -> WebSocket -> index.html."""
    radar_history = []

    while True:
        try:
            async with aiomqtt.Client("127.0.0.1") as client:
                print("Fusion: Publikuji fused data na 'sensors/fused'")

                while True:
                    await asyncio.sleep(0.05)
                    now = time.time()

                    async with lock:
                        new_radar_points = list(shared_state["radar_points"])
                        shared_state["radar_points"].clear()

                        ble_1_count = len(shared_state["ble_tags"]["ble_1"])
                        ble_2_count = len(shared_state["ble_tags"]["ble_2"])
                        out_ble = []
                        common_tags = set(shared_state["ble_tags"]["ble_1"].keys()) & set(
                            shared_state["ble_tags"]["ble_2"].keys()
                        )
                        for tag_id in common_tags:
                            pos = triangulate(tag_id)
                            if pos:
                                out_ble.append({"tag_id": tag_id, "x": pos[0], "y": pos[1]})

                    for point in new_radar_points:
                        point = dict(point)
                        point["_seen_at"] = now
                        radar_history.append(point)

                    radar_history = [
                        point
                        for point in radar_history
                        if now - point.get("_seen_at", now) <= RAW_RADAR_HISTORY_SECONDS
                    ][-MAX_RAW_RADAR_HISTORY_POINTS:]

                    out_radar = [
                        {key: value for key, value in point.items() if key != "_seen_at"}
                        for point in radar_history
                    ]

                    payload = json.dumps(
                        {
                            "radar": out_radar,
                            "ble": out_ble,
                            "stats": {
                                "timestamp": now,
                                "new_radar_points": len(new_radar_points),
                                "radar_history_points": len(out_radar),
                                "ble_1_tags": ble_1_count,
                                "ble_2_tags": ble_2_count,
                                "common_ble_tags": len(common_tags),
                                "triangulated_ble": len(out_ble),
                            },
                        }
                    )
                    await client.publish("sensors/fused", payload)
        except aiomqtt.MqttError:
            print("Fusion publisher: MQTT connection lost, retrying in 2s...")
            await asyncio.sleep(2)


async def main():
    # Listener sbira raw data z ingestion.py, publisher je posila do app.py.
    await asyncio.gather(mqtt_listener(), fused_publisher())


async def main_fusion():
    """Compatibility entry point used by main.py."""
    await main()


if __name__ == "__main__":
    asyncio.run(main())
