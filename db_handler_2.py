import asyncpg

DB_CONFIG = {
    "user": "postgres",
    "password": "postgres",
    "database": "sensor_data",
    "host": "192.168.X.X", # DOPLŇTE IP ADRESU ZAŘÍZENÍ 1
    "port": 5432,
}

DB_SCHEMA = "public"

class AsyncDBHandler:
    def __init__(self):
        self.pool = None

    async def connect(self):
        if self.pool is None:
            # Připojení k vzdálené DB na Zařízení 1
            self.pool = await asyncpg.create_pool(**DB_CONFIG)
            print(f"Zarizeni 2: Pripojeno k DB na {DB_CONFIG['host']}")

    async def init_tables(self):
        if self.pool is None:
            return
        # Tabulky stačí zinicializovat z centrály,
        # ale spuštění zde ničemu neuškodí (CREATE IF NOT EXISTS).
        async with self.pool.acquire() as conn:
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA}")
            # ... (zbytek SQL příkazů CREATE TABLE z původního souboru)
            print("Zarizeni 2: Kontrola tabulek na centrale dokoncena.")

    async def insert_batch(self, table_name, data_list):
        if not data_list or not self.pool:
            return
        cols = {
            "radar_1": "(timestamp, x, y, z, snr)",
            "radar_2": "(timestamp, x, y, z, snr)",
            "ble_1": "(timestamp, tag_id, rssi, azimuth)",
            "ble_2": "(timestamp, tag_id, rssi, azimuth)",
            "fused_data": "(timestamp, tag_id, x, y, z, confidence)",
        }
        async with self.pool.acquire() as conn:
            placeholders = ",".join([f"${i + 1}" for i in range(len(data_list[0]))])
            query = f"INSERT INTO {DB_SCHEMA}.{table_name} {cols[table_name]} VALUES ({placeholders})"
            await conn.executemany(query, data_list)

db_handler = AsyncDBHandler()