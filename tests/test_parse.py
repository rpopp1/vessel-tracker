import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from collector.providers.aisstream_parse import parse_message
from common.models import PositionMsg, StaticMsg
from tests.samples import POSITION_REPORT, SHIP_STATIC_TANKER, with_position, with_static


def test_position_report_parsed():
    m = parse_message(POSITION_REPORT)
    assert isinstance(m, PositionMsg)
    assert (m.mmsi, m.lat, m.lon, m.sog, m.cog, m.heading, m.nav_status) == (
        636012345, 29.7, -93.9, 12.3, 87.4, 88, 0)
    # nanosecond fraction is truncated to microseconds
    assert m.ts == datetime(2026, 10, 8, 12, 0, 0, 123456, tzinfo=timezone.utc)


@pytest.mark.parametrize(  # Review Focus 3
    "overrides,field",
    [({"Sog": 102.3}, "sog"), ({"Cog": 360}, "cog"), ({"TrueHeading": 511}, "heading")],
)
def test_not_available_values_become_none(overrides, field):
    m = parse_message(with_position(**overrides))
    assert getattr(m, field) is None


@pytest.mark.parametrize(
    "overrides",
    [{"Latitude": 91.0}, {"Longitude": 181.0}, {"Latitude": 0.0, "Longitude": 0.0}],
)
def test_invalid_positions_dropped(overrides):  # Review Focus 3
    assert parse_message(with_position(**overrides)) is None


def test_static_parsed():
    m = parse_message(SHIP_STATIC_TANKER)
    assert isinstance(m, StaticMsg)
    assert m.mmsi == 636012345 and m.imo == 9876543 and m.ship_type_code == 84
    assert m.name == "TEST VLCC" and m.callsign == "D5XX1" and m.destination == "HOUSTON"
    assert m.length_m == 333 and m.beam_m == 58 and m.draught_m == 19.5
    assert m.eta == datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)


def test_zero_dimensions_and_draught_become_none():  # Review Focus 3
    m = parse_message(with_static(Dimension={"A": 0, "B": 0, "C": 0, "D": 0}, MaximumStaticDraught=0))
    assert m.length_m is None and m.beam_m is None and m.draught_m is None


@pytest.mark.parametrize("eta", [{"Month": 0, "Day": 0, "Hour": 24, "Minute": 60},
                                 {"Month": 2, "Day": 31, "Hour": 1, "Minute": 1}])
def test_unavailable_or_impossible_eta_is_none(eta):  # Review Focus 3
    assert parse_message(with_static(Eta=eta)).eta is None


def test_eta_in_the_past_rolls_to_next_year():
    m = parse_message(with_static(Eta={"Month": 1, "Day": 5, "Hour": 0, "Minute": 0}))
    assert m.eta == datetime(2027, 1, 5, 0, 0, tzinfo=timezone.utc)


def test_empty_name_is_empty_string_not_crash():
    m = parse_message(with_static(Name="", Destination="", CallSign=""))
    assert (m.name, m.destination, m.callsign) == ("", "", "")


@pytest.mark.parametrize("raw", [{}, {"MessageType": "Other"}, {"MessageType": "PositionReport"},
                                 {"MessageType": "ShipStaticData", "Message": {}}, {"error": "x"}])
def test_unknown_or_malformed_returns_none(raw):
    assert parse_message(raw) is None


# --- real captured AISstream frames (public AIS data) ---
_REAL = json.loads((Path(__file__).parent / "fixtures" / "aisstream_real_frames.json").read_text(encoding="utf-8"))


def _na(value, na):
    return None if value == na else value


@pytest.mark.parametrize("frame", _REAL["PositionReport"])
def test_real_position_frames_parse(frame):
    p = frame["Message"]["PositionReport"]
    m = parse_message(frame)
    assert isinstance(m, PositionMsg)
    assert (m.mmsi, m.lat, m.lon) == (p["UserID"], p["Latitude"], p["Longitude"])
    assert m.sog == p["Sog"] and m.cog == p["Cog"]
    assert m.heading == (None if p["TrueHeading"] == 511 else p["TrueHeading"])


@pytest.mark.parametrize("frame", _REAL["tanker_static"])
def test_real_tanker_static_frames_parse(frame):
    s = frame["Message"]["ShipStaticData"]
    d = s["Dimension"]
    m = parse_message(frame)
    assert isinstance(m, StaticMsg)
    assert m.mmsi == s["UserID"] and 80 <= m.ship_type_code <= 89
    assert m.length_m == d["A"] + d["B"] > 0
    assert m.beam_m == d["C"] + d["D"] > 0
    assert m.imo == (None if s["ImoNumber"] == 0 else s["ImoNumber"])
    assert (m.eta is None) == (s["Eta"]["Month"] == 0)


def test_real_subscription_confirmation_is_not_data():
    assert len(_REAL["other"]) == 1 and _REAL["other"][0]["MessageType"] == "SubscriptionConfirmation"
    assert parse_message(_REAL["other"][0]) is None


def test_legacy_metadata_spelling_still_tolerated():
    legacy = copy.deepcopy(POSITION_REPORT)
    legacy["Metadata"] = legacy.pop("MetaData")
    assert isinstance(parse_message(legacy), PositionMsg)
    legacy_s = copy.deepcopy(SHIP_STATIC_TANKER)
    legacy_s["Metadata"] = legacy_s.pop("MetaData")
    assert isinstance(parse_message(legacy_s), StaticMsg)
