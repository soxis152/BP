"""Main entrypoint with 3 top-level threads."""

import threading
import time
import asyncio
import sys
import uvicorn

# Windows FIX: Zabránění chybám s event loopem ve více vláknech na Windows
if sys.platform == 'win32':
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
    print("[thread-1] Starting ingestion workers")

    # Poznámka: ingestion.init_db() jsme smazali.
    # Tabulky se vytvoří asynchronně uvnitř db_workeru.
    threading.Thread(target=ingestion.db_worker, daemon=True, name="db_worker").start()

    for cfg in ingestion.RADAR_CONFIGS:
        print(f"[thread-1] Starting radar worker: {cfg['id']}")
        threading.Thread(
            target=ingestion.radar_worker,
            args=(cfg,),
            daemon=True,
            name=f"{cfg['id']}_worker",
        ).start()

    for cfg in ingestion.BLE_CONFIGS:
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
    print("[thread-2] Starting fusion loop")
    # OPRAVA: perform_fusion() je asynchronní, musíme ji spustit přes asyncio.run()
    asyncio.run(fusion.perform_fusion())


def api_thread() -> None:
    print("[thread-3] Starting FastAPI server on http://127.0.0.1:8000")
    # Zde máte správně reload=False, v běžícím vlákně uvicorn reload nepodporuje
    uvicorn.run(web_app.app, host="127.0.0.1", port=8000, reload=False)


def main() -> None:
    threads = [
        threading.Thread(target=ingestion_thread, name="ingestion_thread", daemon=True),
        threading.Thread(target=fusion_thread, name="fusion_thread", daemon=True),
        threading.Thread(target=api_thread, name="api_thread", daemon=True),
    ]

    for thread in threads:
        print(f"[main] Launching {thread.name}")
        thread.start()

    print("[main] All 3 threads started. Press Ctrl+C to stop.")

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