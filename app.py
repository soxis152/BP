"""Webova vrstva systemu.

Modul slouzi jako tenky most mezi MQTT streamy a prohlizecem:

- naserviruje `index.html`,
- posloucha `sensors/fused` i pomocne referencni streamy,
- sklada je do jednoho websocket payloadu pro dashboard.

Matematika ani rozhodovani o identite objektu sem nepatri. Pokud se zmeni
fusion algoritmus, tahle vrstva by mela zustat stejna, pokud zustane zachovany
JSON format zprav.
"""

import asyncio
import json
import sys
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import aiomqtt
import asyncpg
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

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
OPTITRACK_REFERENCE_TOPIC = "sensors/reference/optitrack"
latest_fused_payload = None
latest_optitrack_payload = None
replay_frame_cache_path = None
replay_timeline_cache_path = None


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


def configure_replay_frame_cache(path: str | Path | None) -> None:
    """Nastavi volitelnou NDJSON cache pro preload replay frame bufferu."""
    global replay_frame_cache_path

    if not path:
        replay_frame_cache_path = None
        return

    replay_frame_cache_path = Path(path).resolve()


def configure_replay_timeline_cache(path: str | Path | None) -> None:
    """Nastavi volitelnou NDJSON timeline cache pro frame-based replay."""
    global replay_timeline_cache_path

    if not path:
        replay_timeline_cache_path = None
        return

    replay_timeline_cache_path = Path(path).resolve()


def iter_replay_frame_payload_lines(cache_path: Path):
    """Vrati textove payload radky pro preload dashboardu z NDJSON datasetu."""
    with cache_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                yield line
                continue

            payload_text = record.get("payload_text")
            if isinstance(payload_text, str) and payload_text.strip():
                yield payload_text.strip()
                continue

            yield json.dumps(record, ensure_ascii=False)


def render_index_html(index_path: Path) -> str:
    """Nacte dashboard HTML a doplni runtime konfiguraci z Pythonu."""
    html = index_path.read_text(encoding="utf-8")
    return html.replace(
        "__FOUR_DASHBOARD_VIEW_CONFIG__",
        json.dumps(DASHBOARD_VIEW_CONFIG, ensure_ascii=False),
    )


def build_empty_fused_payload() -> dict:
    return {
        "radar": [],
        "radar_clusters": [],
        "ble": [],
        "ble_1_raw": [],
        "ble_2_raw": [],
        "objects": [],
        "stats": None,
    }


def build_dashboard_payload() -> dict:
    fused_payload = latest_fused_payload or build_empty_fused_payload()
    payload = dict(fused_payload)

    optitrack_payload = latest_optitrack_payload or {}
    payload["optitrack_objects"] = list(optitrack_payload.get("objects", []))
    payload["optitrack_stats"] = optitrack_payload.get("stats")
    return payload


async def broadcast_dashboard_payload() -> None:
    if not active_websockets:
        return

    payload_text = json.dumps(build_dashboard_payload(), ensure_ascii=False)
    for websocket in active_websockets.copy():
        try:
            await websocket.send_text(payload_text)
        except Exception:
            if websocket in active_websockets:
                active_websockets.remove(websocket)


async def mqtt_listener():
    """Posloucha fused a referencni MQTT zpravy a rozesila je dashboardum."""
    global latest_fused_payload, latest_optitrack_payload

    while True:
        try:
            async with aiomqtt.Client(MQTT_HOST) as client:
                await client.subscribe("sensors/fused")
                await client.subscribe(OPTITRACK_REFERENCE_TOPIC)
                print(
                    "App: Listening on MQTT topics "
                    "'sensors/fused' and "
                    f"'{OPTITRACK_REFERENCE_TOPIC}'"
                )

                async for message in client.messages:
                    topic = str(message.topic)
                    payload = json.loads(message.payload.decode())

                    if topic == "sensors/fused":
                        latest_fused_payload = payload
                    elif topic == OPTITRACK_REFERENCE_TOPIC:
                        latest_optitrack_payload = payload
                    else:
                        continue

                    await broadcast_dashboard_payload()
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


@app.get("/api/replay/frames")
async def get_replay_frames():
    """Vrati predpocitanou NDJSON cache replay snimku, kdyz je dostupna."""
    if not replay_frame_cache_path or not replay_frame_cache_path.exists():
        return Response(status_code=404)

    return PlainTextResponse(
        "\n".join(iter_replay_frame_payload_lines(replay_frame_cache_path)),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/api/replay/timeline")
async def get_replay_timeline():
    """Vrati predpocitanou timeline cache nad presnou frame osou replaye."""
    if not replay_timeline_cache_path or not replay_timeline_cache_path.exists():
        return Response(status_code=404)

    return PlainTextResponse(
        replay_timeline_cache_path.read_text(encoding="utf-8"),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Drzi websocket spojeni s jednim oknem dashboardu."""
    await websocket.accept()
    active_websockets.append(websocket)
    await websocket.send_text(json.dumps(build_dashboard_payload(), ensure_ascii=False))

    try:
        while True:
            # Dashboard sem neposila ridici prikazy. Cekani na zpravu jen drzi
            # endpoint otevreny a detekuje disconnect.
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)
