from __future__ import annotations

import asyncio
import logging
import time

import psycopg

from collector.pipeline import Pipeline
from collector.providers.aisstream import AISStreamProvider
from collector.store import Store
from common.config import load_config
from common.database import connect
from db.partitions import ensure_month_partitions

log = logging.getLogger("collector")


async def run() -> None:
    cfg = load_config()
    store = Store(connect())
    ensure_month_partitions(store.conn)
    pipeline = Pipeline(store, cfg, store.load_tanker_states())
    provider = AISStreamProvider()
    last_partition_check = last_report = time.monotonic()
    async for msg in provider.messages():
        try:
            pipeline.handle(msg)
        except psycopg.OperationalError:
            log.exception("database connection lost; reconnecting in 5 s")
            await asyncio.sleep(5)
            store.conn = connect()
        now = time.monotonic()
        if now - last_partition_check > 3600:
            ensure_month_partitions(store.conn)
            last_partition_check = now
        if now - last_report > 60:
            log.info("known_tankers=%d dropped=%d %s", len(pipeline.tankers), provider.dropped, pipeline.counters)
            last_report = now


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
