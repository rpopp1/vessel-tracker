from __future__ import annotations

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


def filters_from_json(d: dict) -> VesselFilters:
    """Build filters from a websocket subscription message. Garbage yields defaults."""
    try:
        bbox = d.get("bbox")
        bbox = tuple(float(x) for x in bbox) if bbox is not None else None
        if bbox is not None and len(bbox) != 4:
            bbox = None
        return VesselFilters(
            bbox=bbox,
            size_class=tuple(d.get("size_class") or ()),
            cargo_group=tuple(d.get("cargo_group") or ()),
            laden=d.get("laden"),
            flag=tuple(d.get("flag") or ()),
            nav_status=tuple(int(x) for x in (d.get("nav_status") or ())),
            min_speed=None if d.get("min_speed") is None else float(d["min_speed"]),
            max_speed=None if d.get("max_speed") is None else float(d["max_speed"]),
        )
    except (TypeError, ValueError):
        return VesselFilters()
