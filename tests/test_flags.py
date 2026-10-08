from common.flags import flag_from_mmsi


def test_known_flags():
    assert flag_from_mmsi(351000000) == "Panama"
    assert flag_from_mmsi(636012345) == "Liberia"
    assert flag_from_mmsi(538000001) == "Marshall Islands"


def test_unknown_and_malformed_mmsi():
    assert flag_from_mmsi(999000000) == "Other"
    assert flag_from_mmsi(12345) == "Other"          # not a 9-digit vessel MMSI
