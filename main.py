"""Hlavni vstupni bod celeho systemu.

Soubor jen sklada dohromady tri samostatne casti:

- ingestion: cteni senzoru, MQTT publish a DB zapis,
- fusion: online zpracovani raw dat,
- API: FastAPI server s dashboardem.

Vse bezi v jednom procesu kvuli jednoduche lokalni demonstraci. Protoze spolu
casti komunikuji pres MQTT, lze je pozdeji spustit i jako samostatne procesy.
"""

import asyncio
import sys
import threading
import time

import uvicorn

try:
    from config import API_HOST, API_PORT, ENABLED_SENSORS, INGEST_ENABLE_DB, NODE_ROLE
except ImportError:
    from .config import API_HOST, API_PORT, ENABLED_SENSORS, INGEST_ENABLE_DB, NODE_ROLE

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

try:
    import app as web_app
    import fusion
    import ingestion
except ImportError:
    from . import app as web_app
    from . import fusion
    from . import ingestion


def ingestion_thread() -> None:
    """Spusti workery pro sber raw dat."""
    print("[thread-1] Starting ingestion workers")

    if INGEST_ENABLE_DB:
        threading.Thread(target=ingestion.db_worker, daemon=True, name="db_worker").start()
        print("[thread-1] DB worker enabled")
    else:
        print("[thread-1] DB worker disabled by FOUR_INGEST_ENABLE_DB=0")

    for cfg in ingestion.RADAR_CONFIGS:
        if cfg["id"] not in ENABLED_SENSORS:
            print(f"[thread-1] Skipping radar worker: {cfg['id']}")
            continue

        print(f"[thread-1] Starting radar worker: {cfg['id']}")
        threading.Thread(
            target=ingestion.radar_worker,
            args=(cfg,),
            daemon=True,
            name=f"{cfg['id']}_worker",
        ).start()
        time.sleep(2)

    for cfg in ingestion.BLE_CONFIGS:
        if cfg["id"] not in ENABLED_SENSORS:
            print(f"[thread-1] Skipping BLE worker: {cfg['id']}")
            continue

        print(f"[thread-1] Starting BLE worker: {cfg['id']}")
        threading.Thread(
            target=ingestion.ble_worker,
            args=(cfg,),
            daemon=True,
            name=f"{cfg['id']}_worker",
        ).start()

    print("[thread-1] Ingestion is running")
    while True:
        time.sleep(1)


def fusion_thread() -> None:
    """Spusti fusion engine ve vlastnim asyncio loopu."""
    while True:
        print("[thread-2] Starting fusion loop")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(fusion.main_fusion())
        except OSError as exc:
            # Na Windows se muze pri zahlceni MQTT/WebSocket socketu objevit
            # WinError 10055 primo v event loopu. Fusion potom radsi obnovim,
            # nez aby zbytek mereni bezel bez fused vrstvy.
            print(f"[thread-2] Fusion socket error, restarting in 2s: {exc}")
            time.sleep(2)
        finally:
            loop.close()


def api_thread() -> None:
    """Spusti FastAPI server s dashboardem."""
    print(f"[thread-3] Starting FastAPI server on http://{API_HOST}:{API_PORT}")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    config = uvicorn.Config(web_app.app, host=API_HOST, port=API_PORT, reload=False, loop="asyncio")
    server = uvicorn.Server(config)
    loop.run_until_complete(server.serve())


def main() -> None:
    """Spusti vybrane casti podle role uzlu a hlida, jestli vlakna nezemrela."""
    threads = []

    if NODE_ROLE in ("all", "central", "edge", "ingestion"):
        threads.append(threading.Thread(target=ingestion_thread, name="ingestion_thread", daemon=True))

    if NODE_ROLE in ("all", "central", "fusion"):
        threads.append(threading.Thread(target=fusion_thread, name="fusion_thread", daemon=True))

    if NODE_ROLE in ("all", "central", "api"):
        threads.append(threading.Thread(target=api_thread, name="api_thread", daemon=True))

    if not threads:
        raise RuntimeError(
            f"FOUR_NODE_ROLE='{NODE_ROLE}' did not enable any thread. "
            "Use one of: all, central, edge, ingestion, fusion, api."
        )

    for thread in threads:
        print(f"[main] Launching {thread.name}")
        thread.start()

    print(f"[main] Started {len(threads)} thread(s) for role '{NODE_ROLE}'. Press Ctrl+C to stop.")

    try:
        while True:
            for thread in threads:
                if not thread.is_alive():
                    print(f"[main] WARNING: {thread.name} stopped unexpectedly!")
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n[main] Shutdown requested. Exiting...")


if __name__ == "__main__":
    main()
