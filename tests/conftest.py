import os

import psycopg.rows
import pytest

from common.database import connect, database_url
from db.partitions import ensure_month_partitions
from tests.guards import check_test_target

_TRUNCATE = "TRUNCATE latest_position, positions, vessels CASCADE"


@pytest.fixture(scope="session")
def db_ready():
    try:
        database_url(test=True)
    except RuntimeError:
        pytest.skip("TEST_DATABASE_URL not set")
    err = check_test_target(os.environ.get("TEST_DATABASE_URL"), os.environ.get("DATABASE_URL"), None)
    if err:
        pytest.fail(err, pytrace=False)


@pytest.fixture
def db(db_ready):
    conn = connect(test=True)
    try:
        name = conn.execute("SELECT current_database()").fetchone()[0]
        err = check_test_target(os.environ.get("TEST_DATABASE_URL"), os.environ.get("DATABASE_URL"), name)
        if err:
            pytest.fail(err, pytrace=False)
        conn.row_factory = psycopg.rows.dict_row  # rows are dicts, matching the API's connections
        ensure_month_partitions(conn)  # current + next 2 months, before any row is inserted
        conn.execute(_TRUNCATE)
        yield conn
        conn.execute(_TRUNCATE)  # leave nothing behind (e.g. rows in positions_default)
    finally:
        conn.close()
