import re
from datetime import date, datetime, timezone

import psycopg
import pytest

from common.database import database_url
import db.partitions as partitions
from db.partitions import add_months, ensure_month_partitions, prune_old_partitions


def _partitions(db):
    rows = db.execute(
        "SELECT c.relname FROM pg_inherits i "
        "JOIN pg_class c ON c.oid = i.inhrelid "
        "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'positions'"
    ).fetchall()
    return {r["relname"] for r in rows}


def test_add_months_rolls_over_years():
    assert add_months(date(2026, 11, 20), 2) == date(2027, 1, 1)
    assert add_months(date(2026, 1, 5), -1) == date(2025, 12, 1)


def test_ensure_creates_partitions_and_prune_drops_old_ones(db):
    names = ensure_month_partitions(db, today=date(2020, 1, 15))
    assert names == ["positions_2020_01", "positions_2020_02", "positions_2020_03"]
    assert ensure_month_partitions(db, today=date(2020, 1, 15)) == names  # idempotent
    today = datetime.now(timezone.utc).date()  # same default window as ensure_month_partitions; the db fixture created it
    dropped = prune_old_partitions(db, keep_months=3, today=date(2026, 10, 8))
    assert set(names) <= set(dropped)
    cutoff = add_months(date(2026, 10, 8), -3)
    for name in dropped:
        m = re.fullmatch(r"positions_(\d{4})_(\d{2})", name)
        assert m and date(int(m.group(1)), int(m.group(2)), 1) < cutoff
    remaining = _partitions(db)
    assert "positions_default" in remaining
    assert f"positions_{today:%Y_%m}" in remaining
    assert f"positions_{add_months(today, 1):%Y_%m}" in remaining


def test_partition_functions_require_autocommit(db_ready):
    conn = psycopg.connect(database_url(test=True))  # autocommit off
    try:
        with pytest.raises(RuntimeError, match="autocommit"):
            ensure_month_partitions(conn, today=date(2019, 1, 15))
        with pytest.raises(RuntimeError, match="autocommit"):
            prune_old_partitions(conn, keep_months=3, today=date(2026, 10, 8))
        conn.rollback()
        exists = conn.execute("SELECT to_regclass('positions_2019_01') IS NOT NULL").fetchone()[0]
        assert not exists
    finally:
        conn.close()


def test_db_fixture_creates_current_and_next_partitions(db):
    today = datetime.now(timezone.utc).date()
    have = _partitions(db)
    for i in range(3):
        assert f"positions_{add_months(today, i):%Y_%m}" in have


def test_row_at_now_lands_in_month_partition_not_default(db):
    db.execute("INSERT INTO vessels (mmsi, ship_type_code) VALUES (1, 80)")
    db.execute("INSERT INTO positions (mmsi, ts, geom) VALUES (1, now(), ST_SetSRID(ST_MakePoint(0,0),4326))")
    table = db.execute("SELECT tableoid::regclass::text AS t FROM positions WHERE mmsi = 1").fetchone()["t"]
    assert table != "positions_default"
    assert table == f"positions_{datetime.now(timezone.utc):%Y_%m}"


class _FailingFor:
    """Autocommit connection proxy whose DDL fails for chosen partition names."""

    autocommit = True

    def __init__(self, bad):
        self.bad, self.executed = bad, []

    def execute(self, sql):
        name = sql.split()[5]
        if name in self.bad:
            raise psycopg.errors.DuplicateTable("boom")
        self.executed.append(name)


def test_one_failing_month_does_not_stop_later_months_and_error_names_it():
    conn = _FailingFor({"positions_2020_01"})
    with pytest.raises(RuntimeError) as ei:
        ensure_month_partitions(conn, today=date(2020, 1, 15))
    assert conn.executed == ["positions_2020_02", "positions_2020_03"]
    assert "positions_2020_01" in str(ei.value) and "2020_02" not in str(ei.value)


def test_multiple_failures_are_aggregated_in_one_error():
    conn = _FailingFor({"positions_2020_01", "positions_2020_03"})
    with pytest.raises(RuntimeError) as ei:
        ensure_month_partitions(conn, today=date(2020, 1, 15))
    assert "positions_2020_01" in str(ei.value) and "positions_2020_03" in str(ei.value)
    assert conn.executed == ["positions_2020_02"]


def test_default_today_is_utc_date(monkeypatch):
    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return cls(2031, 12, 31, 23, 30, tzinfo=timezone.utc)

    monkeypatch.setattr(partitions, "datetime", FakeDT)
    conn = _FailingFor(set())
    assert ensure_month_partitions(conn) == ["positions_2031_12", "positions_2032_01", "positions_2032_02"]
