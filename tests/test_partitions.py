import re
from datetime import date

import psycopg
import pytest

from common.database import database_url
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
    today = date.today()
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
