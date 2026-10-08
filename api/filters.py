from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class VesselFilters:
    bbox: tuple[float, float, float, float] | None = None  # west, south, east, north
    size_class: tuple[str, ...] = ()
    cargo_group: tuple[str, ...] = ()
    laden: bool | None = None
    flag: tuple[str, ...] = ()
    nav_status: tuple[int, ...] = ()
    min_speed: float | None = None
    max_speed: float | None = None


def build_where(f: VesselFilters, stale_hours: float, skip: str | None = None) -> tuple[str, list]:
    """WHERE clause over `latest_position lp JOIN vessels v`. `skip` omits one filter dimension (for facet counts)."""
    clauses = ["lp.ts > now() - %s::float8 * interval '1 hour'"]
    params: list = [stale_hours]
    if f.bbox is not None and skip != "bbox":
        w, s, e, n = f.bbox
        if w > e:  # view crosses the antimeridian
            clauses.append(
                "(lp.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326) OR lp.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326))"
            )
            params += [w, s, 180, n, -180, s, e, n]
        else:
            clauses.append("lp.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)")
            params += [w, s, e, n]
    if f.size_class and skip != "size_class":
        clauses.append("v.size_class = ANY(%s)")
        params.append(list(f.size_class))
    if f.cargo_group and skip != "cargo_group":
        clauses.append("v.cargo_group = ANY(%s)")
        params.append(list(f.cargo_group))
    if f.laden is not None and skip != "laden":
        clauses.append("v.laden = %s")
        params.append(f.laden)
    if f.flag and skip != "flag":
        clauses.append("v.flag = ANY(%s)")
        params.append(list(f.flag))
    if f.nav_status and skip != "nav_status":
        clauses.append("lp.nav_status = ANY(%s)")
        params.append(list(f.nav_status))
    if f.min_speed is not None:
        clauses.append("lp.sog >= %s")
        params.append(f.min_speed)
    if f.max_speed is not None:
        clauses.append("lp.sog <= %s")
        params.append(f.max_speed)
    return " AND ".join(clauses), params


MAX_LIST_ITEMS = 50


def _finite(x) -> float | None:
    if isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if math.isfinite(v) else None


def _str_list(v) -> tuple[str, ...]:
    if not isinstance(v, (list, tuple)):
        return ()
    return tuple(str(x) for x in v[:MAX_LIST_ITEMS] if isinstance(x, (str, int)) and not isinstance(x, bool))


def _int_list(v) -> tuple[int, ...]:
    if not isinstance(v, (list, tuple)):
        return ()
    out = []
    for x in v:
        if isinstance(x, bool) or not isinstance(x, (str, int)):
            continue
        try:
            out.append(int(x))
        except ValueError:
            continue
        if len(out) >= MAX_LIST_ITEMS:
            break
    return tuple(out)


def _bbox(v) -> tuple[float, float, float, float] | None:
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        return None
    vals = [_finite(x) for x in v]
    if any(x is None for x in vals):
        return None
    w, s, e, n = vals
    if not (-90 <= s <= 90 and -90 <= n <= 90 and -180 <= w <= 180 and -180 <= e <= 180):
        return None
    return (w, s, e, n)


def filters_from_json(d) -> VesselFilters:
    """Build filters from a websocket subscription message. Never raises; each bad field falls back to its default."""
    if not isinstance(d, dict):
        return VesselFilters()
    laden = d.get("laden")
    return VesselFilters(
        bbox=_bbox(d.get("bbox")),
        size_class=_str_list(d.get("size_class")),
        cargo_group=_str_list(d.get("cargo_group")),
        laden=laden if isinstance(laden, bool) else None,
        flag=_str_list(d.get("flag")),
        nav_status=_int_list(d.get("nav_status")),
        min_speed=_finite(d.get("min_speed")),
        max_speed=_finite(d.get("max_speed")),
    )
