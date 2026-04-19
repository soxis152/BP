"""Rychla kontrola velikosti databazovych tabulek.

Database Explorer v IDE casto zobrazuje jen prvnich par set radku. To neni
limit PostgreSQL ani limit tabulky, jen limit nahledu v klientovi. Tenhle
skript se pta primo databaze a vypise skutecny pocet radku v kazde tabulce.
"""

import asyncio

import asyncpg

try:
    from config import DB_CONFIG, DB_SCHEMA
except ImportError:
    from .config import DB_CONFIG, DB_SCHEMA


TABLES = ("radar_1", "radar_2", "ble_1", "ble_2", "fused_data")


async def fetch_table_stats(conn, table_name):
    """Vrati pocet radku a velikost jedne tabulky."""
    full_table_name = f"{DB_SCHEMA}.{table_name}"
    row_count = await conn.fetchval(f"SELECT COUNT(*) FROM {full_table_name}")
    table_size = await conn.fetchval("SELECT pg_size_pretty(pg_total_relation_size($1::regclass))", full_table_name)
    return row_count, table_size


async def main():
    pool = await asyncpg.create_pool(**DB_CONFIG)

    try:
        async with pool.acquire() as conn:
            print("Tabulka        Radku        Velikost vcetne indexu")
            print("------------------------------------------------")

            total_rows = 0
            for table_name in TABLES:
                row_count, table_size = await fetch_table_stats(conn, table_name)
                total_rows += row_count
                print(f"{table_name:<13} {row_count:>10}  {table_size}")

            print("------------------------------------------------")
            print(f"{'celkem':<13} {total_rows:>10}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
