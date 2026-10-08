import copy

POSITION_REPORT = {
    "MessageType": "PositionReport",
    "MetaData": {
        "MMSI": 636012345, "ShipName": "TEST VLCC  ", "latitude": 29.7, "longitude": -93.9,
        "time_utc": "2026-10-08 12:00:00.123456789 +0000 UTC",
    },
    "Message": {"PositionReport": {
        "Cog": 87.4, "Latitude": 29.7, "Longitude": -93.9, "MessageID": 1,
        "NavigationalStatus": 0, "Sog": 12.3, "TrueHeading": 88, "UserID": 636012345, "Valid": True,
    }},
}

SHIP_STATIC_TANKER = {
    "MessageType": "ShipStaticData",
    "MetaData": {"MMSI": 636012345, "ShipName": "TEST VLCC",
                 "time_utc": "2026-10-08 12:00:05.000000000 +0000 UTC"},
    "Message": {"ShipStaticData": {
        "CallSign": "D5XX1  ", "Destination": "HOUSTON      ",
        "Dimension": {"A": 300, "B": 33, "C": 30, "D": 28},
        "Eta": {"Day": 15, "Hour": 6, "Minute": 0, "Month": 10},
        "ImoNumber": 9876543, "MaximumStaticDraught": 19.5,
        "Name": "TEST VLCC   ", "Type": 84, "UserID": 636012345,
    }},
}


def with_position(**overrides):
    m = copy.deepcopy(POSITION_REPORT)
    m["Message"]["PositionReport"].update(overrides)
    return m


def with_static(**overrides):
    m = copy.deepcopy(SHIP_STATIC_TANKER)
    m["Message"]["ShipStaticData"].update(overrides)
    return m
