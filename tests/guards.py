from __future__ import annotations


def check_test_target(test_url: str | None, dev_url: str | None, db_name: str | None) -> str | None:
    """Return an error message if DB tests (which TRUNCATE) must not run against this target, else None.

    Never includes either URL in the message. db_name None means "not connected yet": only the URL check applies.
    """
    if test_url and dev_url and test_url == dev_url:
        return "TEST_DATABASE_URL must not equal DATABASE_URL (tests TRUNCATE their database)"
    if db_name is not None and "test" not in db_name.lower():
        return f"refusing to TRUNCATE a database whose name does not contain 'test' (database: {db_name})"
    return None
