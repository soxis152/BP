import asyncio
import time
import asyncpg
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()
db_pool = None
active_websockets = []

# Připojení k vaší asynchronní databázi
DB_CONFIG = {
    "user": "postgres",
    "password": "postgres",
    "database": "sensor_data",
    "host": "127.0.0.1"
}


@app.on_event("startup")
async def startup():
    """Při startu serveru vytvoří připojení k DB a spustí vysílání dat."""
    global db_pool
    db_pool = await asyncpg.create_pool(**DB_CONFIG)
    print("Vizualizace připojena k databázi.")

    # Spustíme smyčku, která bude neustále posílat data do prohlížeče
    asyncio.create_task(broadcast_data())


async def broadcast_data():
    """Čte nejnovější fúzovaná data z databáze a posílá je všem připojeným klientům."""
    while True:
        await asyncio.sleep(0.1)  # Aktualizace 10x za sekundu (10 FPS)

        # Pokud není nikdo připojený na webu, nezatěžujeme databázi
        if not active_websockets or not db_pool:
            continue

        try:
            # Zobrazujeme objekty, které se updatovaly za poslední 0.5 sekundy
            window = time.time() - 0.5
            async with db_pool.acquire() as conn:
                records = await conn.fetch(
                    "SELECT tag_id, x, y, z, confidence FROM fused_data WHERE timestamp > $1",
                    window
                )

            # Pokud máme nějaká data, pošleme je jako JSON přes WebSocket
            if records:
                # Převedeme Record objekty z DB do běžného slovníku
                data = [{"tag_id": r["tag_id"], "x": r["x"], "y": r["y"], "confidence": r["confidence"]} for r in
                        records]

                for ws in active_websockets:
                    try:
                        await ws.send_json({"type": "update", "objects": data})
                    except:
                        pass
        except Exception as e:
            print(f"Chyba při čtení dat pro vizualizaci: {e}")


@app.get("/")
async def get():
    """Při načtení stránky v prohlížeči pošle soubor index.html"""
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return HTMLResponse("<h1>Chyba: Chybí soubor index.html</h1>")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Spravuje připojení jednotlivých prohlížečů přes WebSocket"""
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            # Jen udržujeme spojení naživu
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_websockets.remove(websocket)