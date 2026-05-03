"""Webova vrstva systemu.

Modul slouzi jako tenky most mezi fusion vrstvou a prohlizecem:

- naserviruje `index.html`,
- posloucha MQTT topic `sensors/fused`,
- preposila prijate snapshoty otevrenym dashboardum pres WebSocket.

Matematika ani rozhodovani o identite objektu sem nepatri. Pokud se zmeni
fusion algoritmus, tahle vrstva by mela zustat stejna, pokud zustane zachovany
JSON format zpravy.
"""

import asyncio
import json
import sys
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import aiomqtt
import asyncpg
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

try:
    from config import DASHBOARD_VIEW_CONFIG, DB_CONFIG, MQTT_HOST
except ImportError:
    from .config import DASHBOARD_VIEW_CONFIG, DB_CONFIG, MQTT_HOST

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

db_pool = None
mqtt_listener_task = None
active_websockets = []
BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Inicializuje a korektne ukonci zdroje webove vrstvy."""
    global db_pool, mqtt_listener_task

    # Pool zatim slouzi hlavne jako priprava pro budouci historicke endpointy.
    # Zaroven pri startu rychle ukaze, jestli je databaze dostupna.
    db_pool = await asyncpg.create_pool(**DB_CONFIG)
    print("Web/API connected to database.")

    # Listener bezi na pozadi, aby neblokoval HTTP a WebSocket requesty.
    mqtt_listener_task = asyncio.create_task(mqtt_listener(), name="mqtt_listener")

    try:
        yield
    finally:
        if mqtt_listener_task:
            mqtt_listener_task.cancel()
            with suppress(asyncio.CancelledError):
                await mqtt_listener_task
            mqtt_listener_task = None

        for websocket in active_websockets.copy():
            with suppress(Exception):
                await websocket.close()
        active_websockets.clear()

        if db_pool:
            await db_pool.close()
            db_pool = None
            print("Web/API database pool closed.")


app = FastAPI(lifespan=lifespan)


def render_index_html(index_path: Path) -> str:
    """Nacte dashboard HTML a doplni runtime konfiguraci z Pythonu."""
    html = index_path.read_text(encoding="utf-8")
    return html.replace(
        "__FOUR_DASHBOARD_VIEW_CONFIG__",
        json.dumps(DASHBOARD_VIEW_CONFIG, ensure_ascii=False),
    )


async def mqtt_listener():
    """Posloucha fused MQTT zpravy a rozesila je pripojenym dashboardum."""
    while True:
        try:
            async with aiomqtt.Client(MQTT_HOST) as client:
                await client.subscribe("sensors/fused")
                print("App: Listening on MQTT topic 'sensors/fused'")

                async for message in client.messages:
                    if not active_websockets:
                        continue

                    payload = message.payload.decode()

                    # Iteruji nad kopii, protoze se klient muze odpojit uprostred
                    # rozesilani aktualni zpravy.
                    for websocket in active_websockets.copy():
                        try:
                            await websocket.send_text(payload)
                        except Exception:
                            active_websockets.remove(websocket)
        except aiomqtt.MqttError:
            print("App: MQTT connection lost, retrying in 2s...")
            await asyncio.sleep(2)


@app.get("/")
async def get():
    """Vraci hlavni dashboard HTML."""
    index_path = BASE_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Error: missing index.html</h1>")

    return HTMLResponse(
        render_index_html(index_path),
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Drzi websocket spojeni s jednim oknem dashboardu."""
    await websocket.accept()
    active_websockets.append(websocket)

    try:
        while True:
            # Dashboard sem neposila ridici prikazy. Cekani na zpravu jen drzi
            # endpoint otevreny a detekuje disconnect.
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)
