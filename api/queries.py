from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime

import psycopg

from api.filters import VesselFilters, build_where
from common.config import Config

CLUSTER_ZOOM = 5
MAX_FEATURES = 5000
MAX_TRACK_POINTS = 1000
MAX_TRACK_ROWS = 50000

_FROM = "FROM latest_position lp JOIN vessels v ON v.mmsi = lp.mmsi"
_COLS = """v.mmsi, v.name, v.size_class, v.cargo_group, v.laden, v.flag,
    lp.ts, lp.sog, lp.cog, lp.heading, lp.nav_status,
    ST_X(lp.geom) AS lon, ST_Y(lp.geom) AS lat,
    EXTRACT(EPOCH FROM (now() - lp.ts)) / 3600.0 AS age_h"""
_PROPS = ("mmsi", "name", "size_class", "cargo_group", "laden", "flag", "ts", "sog", "cog", "heading", "nav_status")


def _feature(r: dict) -> dict:
    props = {k: r[k] for k in _PROPS}
    props["age_h"] = float(r["age_h"])
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]}, "properties": props}


def list_vessels(conn: psycopg.Connection, f: VesselFilters, zoom: int | None, cfg: Config) -> dict:
    where, params = build_where(f, cfg.stale_hours)
    if zoom is not None and zoom < CLUSTER_ZOOM:
        cell = 40.0 / (2 ** max(zoom, 0))
        rows = conn.execute(
            f"SELECT count(*) AS count, avg(ST_X(lp.geom)) AS lon, avg(ST_Y(lp.geom)) AS lat "
            f"{_FROM} WHERE {where} GROUP BY ST_SnapToGrid(lp.geom, %s)",
            [*params, cell],
        ).fetchall()
        features = [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
             "properties": {"cluster": True, "count": r["count"]}}
            for r in rows
        ]
        return {"type": "FeatureCollection", "features": features}
    rows = conn.execute(
        f"SELECT {_COLS} {_FROM} WHERE {where} ORDER BY lp.ts DESC LIMIT %s", [*params, MAX_FEATURES]
    ).fetchall()
    return {"type": "FeatureCollection", "features": [_feature(r) for r in rows]}


def updated_since(conn, f: VesselFilters, cursor: tuple[datetime, int], cfg: Config, limit: int = 2000):
    """Rows strictly after the (updated_at, mmsi) cursor; returns (features, new_cursor)."""
    where, params = build_where(f, cfg.stale_hours)
    rows = conn.execute(
        f"SELECT {_COLS}, lp.updated_at {_FROM} WHERE {where} AND (lp.updated_at, lp.mmsi) > (%s, %s) "
        f"ORDER BY lp.updated_at, lp.mmsi LIMIT %s",
        [*params, cursor[0], cursor[1], limit],
    ).fetchall()
    new_cursor = (rows[-1]["updated_at"], rows[-1]["mmsi"]) if rows else cursor
    return [_feature(r) for r in rows], new_cursor


def vessel_detail(conn, mmsi: int) -> dict | None:
    r = conn.execute(
        """SELECT v.*, lp.ts AS pos_ts, ST_X(lp.geom) AS lon, ST_Y(lp.geom) AS lat,
                  lp.sog, lp.cog, lp.heading, lp.nav_status
           FROM vessels v LEFT JOIN latest_position lp ON lp.mmsi = v.mmsi WHERE v.mmsi = %s""",
        (mmsi,),
    ).fetchone()
    if r is None:
        return None
    position = None
    if r["pos_ts"] is not None:
        position = {k: r[k] for k in ("lon", "lat", "sog", "cog", "heading", "nav_status")}
        position["ts"] = r["pos_ts"]
    out = {k: r[k] for k in ("mmsi", "imo", "name", "callsign", "flag", "ship_type_code", "length_m", "beam_m",
                             "size_class", "cargo_group", "classified_by", "draught_m", "laden",
                             "destination", "eta")}
    out["inferred"] = {"cargo_group": True, "laden": True}
    out["position"] = position
    return out


def split_antimeridian(coords: list) -> list:
    if not coords:
        return []
    lines = [[coords[0]]]
    for prev, cur in zip(coords, coords[1:]):
        if abs(cur[0] - prev[0]) > 180:
            lines.append([])
        lines[-1].append(cur)
    return lines


def downsample(items: list, max_points: int) -> list:
    if len(items) <= max_points:
        return items
    step = len(items) / max_points
    out = [items[int(i * step)] for i in range(max_points)]
    out.append(items[-1])
    return out


def vessel_track(conn, mmsi: int, start: datetime, end: datetime) -> dict:
    pred = "mmsi = %s AND ts >= %s AND ts <= %s"
    total = conn.execute(f"SELECT count(*) AS n FROM positions WHERE {pred}", (mmsi, start, end)).fetchone()["n"]
    rows = conn.execute(
        f"SELECT ST_X(geom) AS lon, ST_Y(geom) AS lat FROM positions WHERE {pred} ORDER BY ts DESC LIMIT %s",
        (mmsi, start, end, MAX_TRACK_ROWS),
    ).fetchall()
    rows.reverse()  # newest rows kept, back in chronological order
    coords = downsample([[r["lon"], r["lat"]] for r in rows], MAX_TRACK_POINTS)
    lines = [ln for ln in split_antimeridian(coords) if len(ln) >= 2]
    return {
        "type": "Feature",
        "geometry": {"type": "MultiLineString", "coordinates": lines},
        "properties": {"mmsi": mmsi, "point_count": total, "from": start, "to": end},
    }


def search(conn, q: str, limit: int = 20) -> list[dict]:
    q = q.strip()
    if len(q) < 2 or "\x00" in q:
        return []
    if q.isascii() and q.isdigit():
        if len(q) > 12:
            return []
        n = int(q)
        cond, params = "v.mmsi = %s OR v.imo = %s", [n, n]
    else:
        escaped = re.sub(r"([\\%_])", r"\\\1", q.lower())
        cond, params = "lower(v.name) LIKE %s", [f"%{escaped}%"]
    return conn.execute(
        f"SELECT v.mmsi, v.name, v.imo, v.size_class, v.flag, ST_X(lp.geom) AS lon, ST_Y(lp.geom) AS lat "
        f"FROM vessels v LEFT JOIN latest_position lp ON lp.mmsi = v.mmsi "
        f"WHERE {cond} ORDER BY v.name LIMIT %s",
        [*params, limit],
    ).fetchall()


_FACETS = {
    "size_class": "v.size_class",
    "cargo_group": "v.cargo_group",
    "laden": "v.laden",
    "flag": "v.flag",
    "nav_status": "lp.nav_status",
}
_LADEN = {True: "laden", False: "ballast", None: "unknown"}


def stats(conn, f: VesselFilters, cfg: Config) -> dict:
    f = replace(f, bbox=None)
    where, params = build_where(f, cfg.stale_hours)
    out: dict = {"total": conn.execute(f"SELECT count(*) AS n {_FROM} WHERE {where}", params).fetchone()["n"]}
    for dim, col in _FACETS.items():
        w, p = build_where(f, cfg.stale_hours, skip=dim)
        rows = conn.execute(f"SELECT {col} AS k, count(*) AS n {_FROM} WHERE {w} GROUP BY 1", p).fetchall()
        counts = {}
        for r in rows:
            key = _LADEN[r["k"]] if dim == "laden" else ("unknown" if r["k"] is None else str(r["k"]))
            counts[key] = r["n"]
        out[dim] = counts
    out["newest_ts"] = conn.execute("SELECT max(ts) AS t FROM latest_position").fetchone()["t"]
    return out


def meta(cfg: Config) -> dict:
    classes = [{"name": c.name, "cargo_group": c.cargo_group} for c in cfg.size_classes]
    classes.append({"name": "Unclassified", "cargo_group": "unknown"})
    return {"size_classes": classes, "fade_hours": cfg.fade_hours, "stale_hours": cfg.stale_hours}
