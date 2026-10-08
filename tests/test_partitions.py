from datetime import date

from db.partitions import add_months, ensure_month_partitions, prune_old_partitions


def test_add_months_rolls_over_years():
    assert add_months(date(2026, 11, 20), 2) == date(2027, 1, 1)
    assert add_months(date(2026, 1, 5), -1) == date(2025, 12, 1)


def test_ensure_creates_partitions_and_prune_drops_old_ones(db):
    names = ensure_month_partitions(db, today=date(2020, 1, 15))
    assert names == ["positions_2020_01", "positions_2020_02", "positions_2020_03"]
    assert ensure_month_partitions(db, today=date(2020, 1, 15)) == names  # idempotent
    dropped = prune_old_partitions(db, keep_months=3, today=date(2026, 10, 8))
    assert dropped == names
