"""Hlavní vstupní bod, který skládá celý systém dohromady."""

import asyncio
import sys
import threading
import time

import uvicorn

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


# Tento modul neobsahuje matematiku ani sběr dat.
# Jeho smysl je orchestrace:
# - spustit ingestion vrstvu,
# - spustit fusion vrstvu,
# - spustit webový dashboard,
# a držet tyto části naživu v jednom procesu.


def ingestion_thread() -> None:
    """Spustí sběr syrových dat ze senzorů."""
    print("[thread-1] Starting ingestion workers")

    # Jeden DB worker zapisuje všechna syrová data z fronty.
    threading.Thread(target=ingestion.db_worker, daemon=True, name="db_worker").start()

    # Každý radar dostane vlastní worker vlákno.
    for cfg in ingestion.RADAR_CONFIGS:
        print(f"[thread-1] Starting radar worker: {cfg['id']}")
        threading.Thread(
            target=ingestion.radar_worker,
            args=(cfg,),
            daemon=True,
            name=f"{cfg['id']}_worker",
        ).start()

    # Každá BLE kotva dostane také vlastní worker vlákno.
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
    """Spustí fusion engine ve vlastním asyncio loopu."""
    print("[thread-2] Starting fusion loop")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(fusion.main_fusion())


def api_thread() -> None:
    """Spustí FastAPI server s dashboardem."""
    print("[thread-3] Starting FastAPI server on http://127.0.0.1:8000")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    config = uvicorn.Config(web_app.app, host="127.0.0.1", port=8000, reload=False, loop="asyncio")
    server = uvicorn.Server(config)
    loop.run_until_complete(server.serve())


def main() -> None:
    """Složí dohromady všechny hlavní subsystémy."""

    # Každá velká část systému běží odděleně:
    # - ingestion = sběr syrových dat,
    # - fusion = matematické zpracování,
    # - api = prezentace a websocket přenos do browseru.
    #
    # Vlákna jsou daemon, protože proces chceme ukončovat jako jeden celek.
    threads = [
        # threading.Thread(target=ingestion_thread, name="ingestion_thread", daemon=True),
        threading.Thread(target=fusion_thread, name="fusion_thread", daemon=True),
        threading.Thread(target=api_thread, name="api_thread", daemon=True),
    ]

    for thread in threads:
        print(f"[main] Launching {thread.name}")
        thread.start()

    print("[main] All 3 threads started. Press Ctrl+C to stop.")

    try:
        while True:
            # Jednoduchý watchdog hlavního procesu:
            # pokud některé důležité vlákno umře, chceme to vidět v logu.
            for thread in threads:
                if not thread.is_alive():
                    print(f"[main] WARNING: {thread.name} stopped unexpectedly!")
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n[main] Shutdown requested. Exiting...")


if __name__ == "__main__":
    main()
