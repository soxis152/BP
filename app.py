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

# Tento modul je tenká prezentační vrstva systému.
#
# Jeho úkol není počítat fusion, ale:
# 1. naservírovat `index.html`,
# 2. poslouchat MQTT topic s hotovými fused daty,
# 3. přeposílat tyto hotové snapshoty připojeným websocket klientům.
#
# Prakticky tedy funguje jako most:
#   fusion.py -> MQTT -> app.py -> WebSocket -> index.html
app = FastAPI()

# Pool je zde vytvořený při startu aplikace.
# V aktuální verzi se přímo moc nepoužívá, ale drží aplikaci připravenou
# pro případné API endpointy nad historií dat.
db_pool = None

# V paměti držíme seznam právě připojených dashboardů.
active_websockets = []

DB_CONFIG = {"user": "postgres", "password": "postgres", "database": "sensor_data", "host": "127.0.0.1"}
BASE_DIR = Path(__file__).resolve().parent


@app.on_event("startup")
async def startup():
    """Inicializace webové vrstvy při startu FastAPI."""
    global db_pool
    db_pool = await asyncpg.create_pool(**DB_CONFIG)
    print("Web/API connected to database.")

    # MQTT listener běží na pozadí a neblokuje obsluhu HTTP/WebSocket požadavků.
    asyncio.create_task(mqtt_listener())


async def mqtt_listener():
    """Poslouchá fused MQTT zprávy a rozesílá je všem připojeným dashboardům."""
    while True:
        try:
            async with aiomqtt.Client("127.0.0.1") as client:
                await client.subscribe("sensors/fused")
                print("App: Listening on MQTT topic 'sensors/fused'")

                async for message in client.messages:
                    # Když není připojený žádný dashboard, není komu data posílat.
                    if not active_websockets:
                        continue

                    # Frontend očekává JSON text, takže payload jen dekódujeme a přepošleme dál.
                    payload = message.payload.decode()

                    # Kopie seznamu chrání iteraci pro případ, že se během rozesílání
                    # některý websocket odpojí.
                    for ws in active_websockets.copy():
                        try:
                            await ws.send_text(payload)
                        except Exception:
                            # Pokud klient selže, odstraníme ho ze seznamu aktivních spojení.
                            active_websockets.remove(ws)
        except aiomqtt.MqttError:
            print("App: MQTT connection lost, retrying in 2s...")
            await asyncio.sleep(2)


@app.get("/")
async def get():
    """Vrací hlavní dashboard HTML."""
    index_path = BASE_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Error: missing index.html</h1>")

    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Udržuje websocket spojení s dashboardem."""
    await websocket.accept()

    # Každé připojené okno dashboardu si uložíme do seznamu aktivních klientů.
    active_websockets.append(websocket)

    try:
        while True:
            # Frontend v tomto směru v zásadě nic důležitého neposílá,
            # ale receive_text() udržuje spojení aktivní a detekuje disconnect.
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)
