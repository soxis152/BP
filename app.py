import asyncio
import json
import aiomqtt
import asyncpg
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()
db_pool = None
active_websockets = []

DB_CONFIG = {"user": "postgres", "password": "postgres", "database": "sensor_data", "host": "127.0.0.1"}


@app.on_event("startup")
async def startup():
    global db_pool
    db_pool = await asyncpg.create_pool(**DB_CONFIG)
    print("Web/API připojeno k databázi (pouze pro případné čtení historie).")

    # Spustíme asynchronní task, který bude poslouchat MQTT
    asyncio.create_task(mqtt_listener())


async def mqtt_listener():
    """Poslouchá fúzovaná data z MQTT a posílá je přímo do připojených prohlížečů."""
    while True:
        try:
            async with aiomqtt.Client("127.0.0.1") as client:
                await client.subscribe("sensors/fused")
                print("App: Připojeno k MQTT, poslouchám na topicu 'sensors/fused'")

                async for message in client.messages:
                    if not active_websockets:
                        continue  # Pokud nikdo na webu nečte, data zahodíme

                    # Zpráva dorazila již jako JSON string, jen ji pošleme dál
                    payload = message.payload.decode()

                    for ws in active_websockets.copy():
                        try:
                            await ws.send_text(payload)
                        except Exception:
                            active_websockets.remove(ws)
        except aiomqtt.MqttError:
            print("Ztráta spojení s MQTT brokerem, zkouším znovu za 2s...")
            await asyncio.sleep(2)


@app.get("/")
async def get():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return HTMLResponse("<h1>Chyba: Chybí soubor index.html</h1>")


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