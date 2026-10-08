from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PositionMsg:
    mmsi: int
    ts: datetime
    lat: float
    lon: float
    sog: float | None
    cog: float | None
    heading: int | None
    nav_status: int | None


@dataclass(frozen=True)
class StaticMsg:
    mmsi: int
    ts: datetime
    name: str
    imo: int | None
    callsign: str
    ship_type_code: int | None
    length_m: float | None
    beam_m: float | None
    draught_m: float | None
    destination: str
    eta: datetime | None


@dataclass(frozen=True)
class VesselState:
    mmsi: int
    size_class: str
    length_m: float | None
    draught_m: float | None
    draught_min_m: float | None
    draught_max_m: float | None
    laden: bool | None


AISMessage = PositionMsg | StaticMsg
