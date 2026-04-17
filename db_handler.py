import asyncpg

# Tento modul je jediná společná vrstva pro práci s PostgreSQL.
#
# Smysl oddělení:
# - ingestion zapisuje syrová data senzorů,
# - fusion zapisuje už zpracovaná fused data,
# - případné API endpointy mohou stejný pool používat také.
#
# Díky tomu je konfigurace DB i formát tabulek soustředěný na jednom místě.

DB_CONFIG = {
    "user": "postgres",
    "password": "postgres",
    "database": "sensor_data",
    "host": "127.0.0.1",
    "port": 5432,
}

DB_SCHEMA = "public"


class AsyncDBHandler:
    """Asynchronní obsluha databázového poolu a základních tabulek projektu."""

    def __init__(self):
        # Pool vytváříme líně až při prvním skutečném použití.
        # Díky tomu samotný import modulu neotevírá spojení do databáze.
        self.pool = None

    async def connect(self):
        """Zajistí existenci databázového poolu."""
        if self.pool is None:
            self.pool = await asyncpg.create_pool(**DB_CONFIG)
            print("Asynchronni DB Pool vytvoren.")

    async def init_tables(self):
        """Vytvoří schéma, tabulky a indexy, pokud ještě neexistují.

        Projekt tím pádem nepotřebuje pro základní lokální běh zvláštní migrační krok.
        """
        if self.pool is None:
            return

        async with self.pool.acquire() as conn:
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA}")

            # BLE tabulky obsahují jednotlivá surová měření kotev:
            # timestamp, tag_id, sílu signálu a azimut.
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

            # Radar tabulky ukládají syrové body odrazu převedené do globální mapy místnosti.
            # Přidán sloupec doppler.
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

            # fused_data je už výstup fusion vrstvy:
            # tedy sledovaný objekt po clusteringu, Kalmanovi a identifikační logice.
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

            # Indexy podle času jsou důležité pro historické dotazy a ladění scénářů v čase.
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

            # Indexy podle tag_id urychlují analýzu historie jednoho konkrétního BLE tagu.
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
        """Zapíše dávku řádků do zadané tabulky.

        Všechny zápisy v projektu jdou přes tuto metodu, aby:
        - definice sloupců byla centralizovaná,
        - ingestion i fusion používaly stejnou logiku,
        - nebylo potřeba skládat INSERT ručně na více místech.
        """
        if not data_list or not self.pool:
            return

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


# Sdílená singleton instance používaná napříč projektem.
db_handler = AsyncDBHandler()