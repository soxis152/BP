import asyncio
import sys
import threading
import time

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

try:
    import ingestion_2
except ImportError:
    from . import ingestion_2


def ingestion_2_thread() -> None:
    print("[thread-1] Starting ingestion_2 workers for Device 2")

    threading.Thread(target=ingestion_2.db_worker, daemon=True, name="db_worker").start()

    for cfg in ingestion_2.RADAR_CONFIGS:
        print(f"[thread-1] Starting radar worker: {cfg['id']}")
        threading.Thread(
            target=ingestion_2.radar_worker,
            args=(cfg,),
            daemon=True,
            name=f"{cfg['id']}_worker",
        ).start()

    for cfg in ingestion_2.BLE_CONFIGS:
        print(f"[thread-1] Starting BLE worker: {cfg['id']}")
        threading.Thread(
            target=ingestion_2.ble_worker,
            args=(cfg,),
            daemon=True,
            name=f"{cfg['id']}_worker",
        ).start()

    print("[thread-1] Ingestion_2 is running on Device 2")
    while True:
        time.sleep(1)


def main() -> None:
    # Na Zařízení 2 spouštíme POUZE ingestion_2_thread.
    # API a Fúze běží pouze na centrále (Zařízení 1).
    threads = [
        threading.Thread(target=ingestion_2_thread, name="ingestion_2_thread", daemon=True),
    ]

    for thread in threads:
        print(f"[main] Launching {thread.name} on Device 2")
        thread.start()

    print("[main] Device 2 node started. Sending data to central. Press Ctrl+C to stop.")

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