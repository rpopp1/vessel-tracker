import asyncio
import logging

import psycopg
import pytest

from collector import main as cm


class FakeStore:
    def __init__(self, failures):
        self.failures = list(failures)   # exceptions (or None) to raise, one per handle call
        self.calls = 0
        self.stored = []
        self.conn = "old"


class FakePipeline:
    def __init__(self, store):
        self.store = store
        self.tankers = {}
        self.counters = {"tanker_static": 0}

    def handle(self, msg):
        self.store.calls += 1
        if self.store.failures:
            exc = self.store.failures.pop(0)
            if exc is not None:
                raise exc
        self.store.stored.append(msg)


def setup(failures):
    store = FakeStore(failures)
    reconnects = []

    async def reconnect(s):
        reconnects.append(s)

    reconnect.calls = reconnects
    return store, FakePipeline(store), reconnect, {"handler_errors": 0}


async def test_operational_error_once_is_retried_and_stored():
    store, p, rec, counters = setup([psycopg.OperationalError("x")])
    await cm.handle_with_recovery(p, store, "m", rec, counters)
    assert store.stored == ["m"] and store.calls == 2 and len(rec.calls) == 1
    assert counters["handler_errors"] == 0


async def test_interface_error_is_also_recovered():
    store, p, rec, counters = setup([psycopg.InterfaceError("x")])
    await cm.handle_with_recovery(p, store, "m", rec, counters)
    assert store.stored == ["m"] and len(rec.calls) == 1


async def test_operational_error_twice_is_counted_and_loop_continues():
    store, p, rec, counters = setup([psycopg.OperationalError("x"), psycopg.OperationalError("y")])
    await cm.handle_with_recovery(p, store, "m", rec, counters)
    assert store.stored == [] and store.calls == 2 and counters["handler_errors"] == 1
    await cm.handle_with_recovery(p, store, "m2", rec, counters)   # next message works
    assert store.stored == ["m2"]


async def test_other_exception_is_counted_without_reconnect():
    store, p, rec, counters = setup([ValueError("boom")])
    await cm.handle_with_recovery(p, store, "m", rec, counters)
    assert counters["handler_errors"] == 1 and rec.calls == [] and store.calls == 1


async def test_cancelled_error_is_not_swallowed():
    store, p, rec, counters = setup([asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        await cm.handle_with_recovery(p, store, "m", rec, counters)


async def test_reconnect_backs_off_then_succeeds_and_closes_old(monkeypatch):
    sleeps, attempts = [], []

    async def fake_sleep(d):
        sleeps.append(d)

    class Old:
        closed = False

        def close(self):
            Old.closed = True
            raise RuntimeError("ignored")

    def fake_connect():
        attempts.append(1)
        if len(attempts) < 4:
            raise psycopg.OperationalError("down")
        return "new"

    monkeypatch.setattr(cm, "_sleep", fake_sleep)
    monkeypatch.setattr(cm, "connect", fake_connect)
    store = FakeStore([])
    store.conn = Old()
    await cm.reconnect_db(store)
    assert store.conn == "new" and Old.closed
    assert sleeps == [1.0, 2.0, 4.0]


async def test_reconnect_backoff_caps_at_60(monkeypatch):
    sleeps, attempts = [], []

    async def fake_sleep(d):
        sleeps.append(d)

    def fake_connect():
        attempts.append(1)
        if len(attempts) < 9:
            raise psycopg.OperationalError("down")
        return "new"

    monkeypatch.setattr(cm, "_sleep", fake_sleep)
    monkeypatch.setattr(cm, "connect", fake_connect)
    store = FakeStore([])
    await cm.reconnect_db(store)
    assert sleeps == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]


def test_reconnect_uses_common_database_connect():
    from common.database import connect
    assert cm.connect is connect


def test_partition_guard_logs_and_continues(monkeypatch, caplog):
    def boom(conn):
        raise psycopg.OperationalError("down")

    monkeypatch.setattr(cm, "ensure_month_partitions", boom)
    caplog.set_level(logging.INFO, logger="collector")
    assert cm.safe_ensure_partitions(FakeStore([])) is False
    assert any("partition" in r.getMessage().lower() for r in caplog.records)


async def test_heartbeat_fires_with_zero_traffic(caplog):
    from types import SimpleNamespace
    caplog.set_level(logging.INFO, logger="collector")
    provider = SimpleNamespace(received=0, dropped=0, last_received=None)
    pipeline = SimpleNamespace(tankers={}, counters={"tanker_static": 0})
    task = asyncio.create_task(cm.heartbeat(pipeline, provider, {"handler_errors": 0}, interval=0.01))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    lines = [r.getMessage() for r in caplog.records if "heartbeat" in r.getMessage()]
    assert lines and "received=0" in lines[0] and "never" in lines[0] and "known_tankers=0" in lines[0]
