import psycopg.rows
import pytest

from common.database import connect, database_url


@pytest.fixture(scope="session")
def db_ready():
    try:
        database_url(test=True)
    except RuntimeError:
        pytest.skip("TEST_DATABASE_URL not set")


@pytest.fixture
def db(db_ready):
    conn = connect(test=True)
    conn.row_factory = psycopg.rows.dict_row  # rows are dicts, matching the API's connections
    conn.execute("TRUNCATE latest_position, positions, vessels CASCADE")
    yield conn
    conn.close()
