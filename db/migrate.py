from __future__ import annotations

import sys
from pathlib import Path

import psycopg

from common.database import connect
from db.partitions import ensure_month_partitions

MIGRATIONS = Path(__file__).parent / "migrations"


def apply(conn: psycopg.Connection) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()}
    applied = []
    for f in sorted(MIGRATIONS.glob("*.sql")):
        if f.name in done:
            continue
        with conn.transaction():
            conn.execute(f.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
        applied.append(f.name)
    ensure_month_partitions(conn)
    return applied


def main() -> None:
    conn = connect(test="--test" in sys.argv)
    applied = apply(conn)
    print("applied:", ", ".join(applied) if applied else "nothing to apply")


if __name__ == "__main__":
    main()
