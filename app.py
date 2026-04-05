import asyncio
import json
import sys
from pathlib import Path

import aiomqtt
import asyncpg
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

app = FastAPI()
db_pool = None
active_websockets = []

DB_CONFIG = {"user": "postgres", "password": "postgres", "database": "sensor_data", "host": "127.0.0.1"}
BASE_DIR = Path(__file__).resolve().parent


@app.on_event("startup")
async def startup():
    global db_pool
    db_pool = await asyncpg.create_pool(**DB_CONFIG)
    print("Web/API connected to database.")
    asyncio.create_task(mqtt_listener())


async def mqtt_listener():
    while True:
        try:
            async with aiomqtt.Client("127.0.0.1") as client:
                await client.subscribe("sensors/fused")
                print("App: Listening on MQTT topic 'sensors/fused'")

                async for message in client.messages:
                    if not active_websockets:
                        continue

                    payload = message.payload.decode()

                    for ws in active_websockets.copy():
                        try:
                            await ws.send_text(payload)
                        except Exception:
                            active_websockets.remove(ws)
        except aiomqtt.MqttError:
            print("App: MQTT connection lost, retrying in 2s...")
            await asyncio.sleep(2)


@app.get("/")
async def get():
    index_path = BASE_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Error: missing index.html</h1>")

    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)
