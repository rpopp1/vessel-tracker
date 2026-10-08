import pytest

from collector.classify import UNCLASSIFIED, classify, estimate_laden, is_tanker_type
from common.config import load_config

CFG = load_config()


@pytest.mark.parametrize(
    "length,expected",
    [
        (333, "ULCC/VLCC"), (300, "ULCC/VLCC"), (299.9, "Suezmax"), (260, "Suezmax"),
        (259.9, "Aframax/LR2"), (225, "Aframax/LR2"), (224.9, "Panamax/LR1"), (200, "Panamax/LR1"),
        (199.9, "MR"), (160, "MR"), (159.9, "Handy/small"), (50, "Handy/small"),
    ],
)
def test_size_class_boundaries(length, expected):
    assert classify(length, CFG).size_class == expected


def test_cargo_group_follows_class():
    assert classify(333, CFG).cargo_group == "crude"
    assert classify(240, CFG).cargo_group == "crude_or_products"
    assert classify(180, CFG).cargo_group == "products"


@pytest.mark.parametrize("length", [None, 0, -5])
def test_missing_or_zero_length_is_unclassified(length):  # Review Focus 3
    assert classify(length, CFG) == UNCLASSIFIED


def test_tanker_type_codes():
    assert is_tanker_type(80) and is_tanker_type(89)
    assert not is_tanker_type(79) and not is_tanker_type(90)
    assert not is_tanker_type(None)


def test_laden_from_class_reference_when_no_history():
    # Suezmax reference 15.5 m * 0.8 = 12.4 m
    assert estimate_laden("Suezmax", 14.0, None, None, CFG) is True
    assert estimate_laden("Suezmax", 8.0, None, None, CFG) is False


def test_laden_uses_observed_range_when_wide_enough():
    assert estimate_laden("Suezmax", 13.0, 8.0, 16.0, CFG) is True   # above midpoint 12
    assert estimate_laden("Suezmax", 10.0, 8.0, 16.0, CFG) is False


def test_narrow_observed_range_is_ignored():
    # range 1 m < 3 m, so fall back to class reference (12.4 m)
    assert estimate_laden("Suezmax", 14.0, 13.5, 14.5, CFG) is True


@pytest.mark.parametrize("draught", [None, 0, 0.0])
def test_laden_unknown_without_draught(draught):
    assert estimate_laden("MR", draught, None, None, CFG) is None


def test_laden_unknown_for_unclassified():
    assert estimate_laden("Unclassified", 10.0, None, None, CFG) is None
