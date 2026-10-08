from __future__ import annotations

import re
from datetime import date

import psycopg


def add_months(d: date, n: int) -> date:
    """First day of the month n months after d's month."""
    idx = d.year * 12 + (d.month - 1) + n
    return date(idx // 12, idx % 12 + 1, 1)


def _name(start: date) -> str:
    return f"positions_{start:%Y_%m}"


def ensure_month_partitions(conn: psycopg.Connection, months_ahead: int = 2, today: date | None = None) -> list[str]:
    """Create monthly partitions for this month and the next `months_ahead`.

    Must run before rows for that month are inserted: Postgres refuses to create a
    partition whose range already has rows in the DEFAULT partition.
    """
    today = today or date.today()
    names = []
    for i in range(months_ahead + 1):
        start = add_months(today, i)
        end = add_months(start, 1)
        name = _name(start)  # built from dates only, never from user input
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF positions "
            f"FOR VALUES FROM ('{start} 00:00+00') TO ('{end} 00:00+00')"
        )
        names.append(name)
    return names


def prune_old_partitions(conn: psycopg.Connection, keep_months: int, today: date | None = None) -> list[str]:
    today = today or date.today()
    cutoff = add_months(today, -keep_months)
    rows = conn.execute(
        "SELECT c.relname FROM pg_inherits i "
        "JOIN pg_class c ON c.oid = i.inhrelid "
        "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'positions'"
    ).fetchall()
    dropped = []
    for row in rows:
        name = row["relname"] if isinstance(row, dict) else row[0]
        m = re.fullmatch(r"positions_(\d{4})_(\d{2})", name)
        if m and date(int(m.group(1)), int(m.group(2)), 1) < cutoff:
            conn.execute(f"DROP TABLE {name}")
            dropped.append(name)
    return sorted(dropped)
