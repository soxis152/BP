"""Databazova vrstva projektu.

Vsechny zapisy do PostgreSQL jdou pres tento modul. Zbytek aplikace tak nemusi
znat SQL detaily, nazvy sloupcu ani inicializaci tabulek.

Pro lokalni prototyp pouzivam `CREATE TABLE IF NOT EXISTS`. Je to jednodussi
nez migrace a staci to pro opakovane spousteni mereni na jednom stroji.
"""

import asyncpg

try:
    from config import DB_CONFIG, DB_SCHEMA
except ImportError:
    from .config import DB_CONFIG, DB_SCHEMA


class AsyncDBHandler:
    """Asynchronni obsluha PostgreSQL poolu a zakladnich tabulek."""

    def __init__(self):
        self.pool = None

    async def connect(self):
        """Vytvori connection pool pri prvnim skutecnem pouziti."""
        if self.pool is None:
            self.pool = await asyncpg.create_pool(**DB_CONFIG)
            print("Asynchronni DB Pool vytvoren.")

    async def init_tables(self):
        """Vytvori schema, tabulky a indexy, pokud jeste neexistuji."""
        if self.pool is None:
            return

        async with self.pool.acquire() as conn:
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA}")

            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.ble_1 ("
                "id SERIAL PRIMARY KEY, "
                "timestamp DOUBLE PRECISION, "
                "tag_id TEXT, "
                "rssi INT, "
                "azimuth DOUBLE PRECISION)"
            )
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.ble_2 ("
                "id SERIAL PRIMARY KEY, "
                "timestamp DOUBLE PRECISION, "
                "tag_id TEXT, "
                "rssi INT, "
                "azimuth DOUBLE PRECISION)"
            )

            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.radar_1 ("
                "id SERIAL PRIMARY KEY, "
                "timestamp DOUBLE PRECISION, "
                "x DOUBLE PRECISION, "
                "y DOUBLE PRECISION, "
                "z DOUBLE PRECISION, "
                "snr DOUBLE PRECISION, "
                "doppler DOUBLE PRECISION)"
            )
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.radar_2 ("
                "id SERIAL PRIMARY KEY, "
                "timestamp DOUBLE PRECISION, "
                "x DOUBLE PRECISION, "
                "y DOUBLE PRECISION, "
                "z DOUBLE PRECISION, "
                "snr DOUBLE PRECISION, "
                "doppler DOUBLE PRECISION)"
            )

            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.fused_data ("
                "id SERIAL PRIMARY KEY, "
                "timestamp DOUBLE PRECISION, "
                "tag_id TEXT, "
                "x DOUBLE PRECISION, "
                "y DOUBLE PRECISION, "
                "z DOUBLE PRECISION, "
                "confidence DOUBLE PRECISION)"
            )

            # Casove indexy jsou hlavni pro pozdejsi analyzu prubehu mereni.
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_radar_1_timestamp ON {DB_SCHEMA}.radar_1(timestamp)"
            )
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_radar_2_timestamp ON {DB_SCHEMA}.radar_2(timestamp)"
            )
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_ble_1_timestamp ON {DB_SCHEMA}.ble_1(timestamp)"
            )
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_ble_2_timestamp ON {DB_SCHEMA}.ble_2(timestamp)"
            )
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_fused_timestamp ON {DB_SCHEMA}.fused_data(timestamp)"
            )

            # Tag indexy urychli dotazy na historii jedne konkretni osoby/tagu.
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_ble_1_tag ON {DB_SCHEMA}.ble_1(tag_id)"
            )
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_ble_2_tag ON {DB_SCHEMA}.ble_2(tag_id)"
            )
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_fused_tag ON {DB_SCHEMA}.fused_data(tag_id)"
            )

            print("Tabulky a indexy byly zkontrolovany nebo vytvoreny.")

    async def insert_batch(self, table_name, data_list):
        """Zapise davku radku do zvolene tabulky."""
        if not data_list or not self.pool:
            return

        # Tabulka ani sloupce nejdou bezpecne parametrizovat pres asyncpg
        # placeholdery, proto jsou povolene jen hodnoty z pevne mapy.
        cols = {
            "radar_1": "(timestamp, x, y, z, snr, doppler)",
            "radar_2": "(timestamp, x, y, z, snr, doppler)",
            "ble_1": "(timestamp, tag_id, rssi, azimuth)",
            "ble_2": "(timestamp, tag_id, rssi, azimuth)",
            "fused_data": "(timestamp, tag_id, x, y, z, confidence)",
        }

        async with self.pool.acquire() as conn:
            placeholders = ",".join([f"${i + 1}" for i in range(len(data_list[0]))])
            query = f"INSERT INTO {DB_SCHEMA}.{table_name} {cols[table_name]} VALUES ({placeholders})"
            await conn.executemany(query, data_list)


db_handler = AsyncDBHandler()
