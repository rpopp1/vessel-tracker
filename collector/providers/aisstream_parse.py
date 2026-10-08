from __future__ import annotations

from datetime import datetime, timedelta, timezone

from common.models import AISMessage, PositionMsg, StaticMsg


def parse_message(raw: dict) -> AISMessage | None:
    """Normalize one decoded AISstream message. Returns None for anything unusable."""
    try:
        mtype = raw.get("MessageType")
        if mtype == "PositionReport":
            return _position(raw)
        if mtype == "ShipStaticData":
            return _static(raw)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return None


def _meta(raw: dict) -> dict:
    # the live feed spells it "MetaData"; tolerate the older "Metadata" too
    return raw.get("MetaData") or raw.get("Metadata")


def _parse_ts(s: str) -> datetime:
    date_part, time_part = s.split()[:2]
    fmt = "%Y-%m-%d %H:%M:%S"
    if "." in time_part:
        whole, frac = time_part.split(".")
        time_part = f"{whole}.{frac[:6]}"
        fmt += ".%f"
    return datetime.strptime(f"{date_part} {time_part}", fmt).replace(tzinfo=timezone.utc)


def _position(raw: dict) -> PositionMsg | None:
    p = raw["Message"]["PositionReport"]
    ts = _parse_ts(_meta(raw)["time_utc"])
    lat, lon = float(p["Latitude"]), float(p["Longitude"])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    sog = p.get("Sog")
    cog = p.get("Cog")
    heading = p.get("TrueHeading")
    nav = p.get("NavigationalStatus")
    return PositionMsg(
        mmsi=int(p["UserID"]),
        ts=ts,
        lat=lat,
        lon=lon,
        sog=None if sog is None or sog >= 102.3 else float(sog),
        cog=None if cog is None or cog >= 360 else float(cog),
        heading=None if heading is None or not 0 <= heading < 360 else int(heading),
        nav_status=None if nav is None else int(nav),
    )


def _static(raw: dict) -> StaticMsg:
    s = raw["Message"]["ShipStaticData"]
    ts = _parse_ts(_meta(raw)["time_utc"])
    dim = s.get("Dimension") or {}
    length = (dim.get("A") or 0) + (dim.get("B") or 0)
    beam = (dim.get("C") or 0) + (dim.get("D") or 0)
    draught = s.get("MaximumStaticDraught") or 0
    imo = s.get("ImoNumber") or None
    return StaticMsg(
        mmsi=int(s["UserID"]),
        ts=ts,
        name=(s.get("Name") or "").strip(),
        imo=int(imo) if imo else None,
        callsign=(s.get("CallSign") or "").strip(),
        ship_type_code=s.get("Type"),
        length_m=float(length) if length > 0 else None,
        beam_m=float(beam) if beam > 0 else None,
        draught_m=float(draught) if draught > 0 else None,
        destination=(s.get("Destination") or "").strip(),
        eta=_eta(s.get("Eta") or {}, ts),
    )


def _eta(e: dict, ts: datetime) -> datetime | None:
    month, day = e.get("Month", 0), e.get("Day", 0)
    hour, minute = e.get("Hour", 24), e.get("Minute", 60)
    if not (1 <= month <= 12 and 1 <= day <= 31 and 0 <= hour < 24 and 0 <= minute < 60):
        return None
    try:
        eta = datetime(ts.year, month, day, hour, minute, tzinfo=timezone.utc)
        if eta < ts - timedelta(days=30):
            eta = eta.replace(year=ts.year + 1)
    except ValueError:
        return None
    return eta
