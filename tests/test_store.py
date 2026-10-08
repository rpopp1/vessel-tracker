from datetime import datetime, timedelta, timezone

from collector.classify import Classification
from collector.providers.aisstream_parse import parse_message
from collector.store import Store
from common.models import PositionMsg, VesselState
from tests.samples import SHIP_STATIC_TANKER

STATE = VesselState(636012345, "ULCC/VLCC", 333.0, 19.5, 19.5, 19.5, True)
CLS = Classification("ULCC/VLCC", "crude")
T0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def pos(ts, lon=-93.9):
    return PositionMsg(636012345, ts, 29.7, lon, 12.3, 87.4, 88, 0)


def test_upsert_vessel_and_reload_state(db):
    store = Store(db)
    store.upsert_vessel(parse_message(SHIP_STATIC_TANKER), CLS, STATE)
    row = db.execute("SELECT name, flag, size_class, imo, laden FROM vessels WHERE mmsi = 636012345").fetchone()
    assert tuple(row.values()) == ("TEST VLCC", "Liberia", "ULCC/VLCC", 9876543, True)
    assert store.load_tanker_states()[636012345] == STATE


def test_empty_name_does_not_overwrite_existing(db):
    store = Store(db)
    store.upsert_vessel(parse_message(SHIP_STATIC_TANKER), CLS, STATE)
    blank = parse_message({**SHIP_STATIC_TANKER, "Message": {"ShipStaticData": {
        **SHIP_STATIC_TANKER["Message"]["ShipStaticData"], "Name": ""}}})
    store.upsert_vessel(blank, CLS, STATE)
    assert db.execute("SELECT name FROM vessels").fetchone()["name"] == "TEST VLCC"


def test_positions_stored_and_latest_only_moves_forward(db):
    store = Store(db)
    store.upsert_vessel(parse_message(SHIP_STATIC_TANKER), CLS, STATE)
    store.add_position(pos(T0 + timedelta(minutes=5), lon=-90.0), 19.5)
    store.add_position(pos(T0, lon=-95.0), 19.5)                    # older: history only
    store.add_position(pos(T0, lon=-95.0), 19.5)                    # duplicate (mmsi, ts): ignored
    assert db.execute("SELECT count(*) AS n FROM positions").fetchone()["n"] == 2
    lon = db.execute("SELECT ST_X(geom) AS lon FROM latest_position").fetchone()["lon"]
    assert lon == -90.0
