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

HEARTBEAT_INTERVAL = 60.0
PARTITION_CHECK_INTERVAL = 3600.0
RECONNECT_START = 1.0
RECONNECT_CAP = 60.0


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def reconnect_db(store: Store) -> None:
    """Replace store.conn with a fresh autocommit connection (common.database.connect), retrying with backoff."""
    try:
        store.conn.close()
    except Exception:  # old connection may already be dead
        pass
    delay = RECONNECT_START
    while True:
        try:
            store.conn = connect()
            log.info("database reconnected")
            return
        except Exception as exc:  # CancelledError/KeyboardInterrupt are BaseException and propagate
            log.warning("database reconnect failed (%s); retrying in %.0f s", type(exc).__name__, delay)
            await _sleep(delay)
            delay = min(delay * 2, RECONNECT_CAP)


async def handle_with_recovery(pipeline, store, msg, reconnect, counters: dict[str, int]) -> None:
    """Handle one message. A database error triggers reconnect and ONE retry of the same message;
    a second failure, or any non-database exception, is logged and counted, never fatal."""
    try:
        pipeline.handle(msg)
        return
    except psycopg.Error as exc:
        log.exception("database error handling message (%s); reconnecting", type(exc).__name__)
    except Exception as exc:
        log.exception("error handling message (%s): %s", type(exc).__name__, exc)
        counters["handler_errors"] += 1
        return
    await reconnect(store)
    try:
        pipeline.handle(msg)
    except Exception as exc:
        log.exception("retry after reconnect failed (%s): %s", type(exc).__name__, exc)
        counters["handler_errors"] += 1


def safe_ensure_partitions(store: Store) -> bool:
    try:
        ensure_month_partitions(store.conn)
        return True
    except Exception as exc:
        log.warning("partition check failed (%s); will retry next interval", type(exc).__name__)
        return False


async def heartbeat(pipeline, provider, counters: dict[str, int], interval: float = HEARTBEAT_INTERVAL) -> None:
    """Periodic status line, independent of message traffic."""
    while True:
        await asyncio.sleep(interval)
        last = provider.last_received
        since = "never" if last is None else "%.0fs" % (time.monotonic() - last)
        log.info(
            "heartbeat known_tankers=%d received=%d dropped=%d last_frame=%s handler_errors=%d %s",
            len(pipeline.tankers), provider.received, provider.dropped, since,
            counters["handler_errors"], pipeline.counters,
        )


async def run() -> None:
    cfg = load_config()
    log.info("collector starting; config loaded")
    store = Store(None)  # type: ignore[arg-type]
    await reconnect_db(store)  # retries with backoff if the database is unreachable
    safe_ensure_partitions(store)
    tankers = store.load_tanker_states()
    log.info("database connected, partitions ensured, known_tankers=%d loaded", len(tankers))
    pipeline = Pipeline(store, cfg, tankers)
    provider = AISStreamProvider()
    counters = {"handler_errors": 0}
    hb = asyncio.create_task(heartbeat(pipeline, provider, counters))
    last_partition_check = time.monotonic()
    try:
        async for msg in provider.messages():
            await handle_with_recovery(pipeline, store, msg, reconnect_db, counters)
            now = time.monotonic()
            if now - last_partition_check > PARTITION_CHECK_INTERVAL:
                safe_ensure_partitions(store)
                last_partition_check = now
    finally:
        hb.cancel()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
