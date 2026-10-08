from __future__ import annotations

import os

import psycopg


def database_url(test: bool = False) -> str:
    name = "TEST_DATABASE_URL" if test else "DATABASE_URL"
    url = os.environ.get(name)
    if not url:
        raise RuntimeError(f"{name} environment variable is not set")
    return url


def connect(test: bool = False) -> psycopg.Connection:
    return psycopg.connect(database_url(test), autocommit=True)
