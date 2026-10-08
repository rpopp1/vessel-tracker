from __future__ import annotations

import psycopg
import psycopg.rows

from collector.classify import Classification
from common.flags import flag_from_mmsi
from common.models import PositionMsg, StaticMsg, VesselState


class Store:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def upsert_vessel(self, msg: StaticMsg, cls: Classification, state: VesselState) -> None:
        self.conn.execute(
            """
            INSERT INTO vessels (mmsi, imo, name, callsign, flag, ship_type_code, length_m, beam_m,
                size_class, cargo_group, draught_m, draught_min_m, draught_max_m, laden,
                destination, eta, updated_at)
            VALUES (%(mmsi)s, %(imo)s, %(name)s, %(callsign)s, %(flag)s, %(type)s, %(length)s, %(beam)s,
                %(size_class)s, %(cargo_group)s, %(draught)s, %(dmin)s, %(dmax)s, %(laden)s,
                %(dest)s, %(eta)s, now())
            ON CONFLICT (mmsi) DO UPDATE SET
                imo = COALESCE(EXCLUDED.imo, vessels.imo),
                name = COALESCE(NULLIF(EXCLUDED.name, ''), vessels.name),
                callsign = COALESCE(NULLIF(EXCLUDED.callsign, ''), vessels.callsign),
                ship_type_code = EXCLUDED.ship_type_code,
                length_m = COALESCE(EXCLUDED.length_m, vessels.length_m),
                beam_m = COALESCE(EXCLUDED.beam_m, vessels.beam_m),
                size_class = EXCLUDED.size_class, cargo_group = EXCLUDED.cargo_group,
                draught_m = EXCLUDED.draught_m, draught_min_m = EXCLUDED.draught_min_m,
                draught_max_m = EXCLUDED.draught_max_m, laden = EXCLUDED.laden,
                destination = COALESCE(NULLIF(EXCLUDED.destination, ''), vessels.destination),
                eta = EXCLUDED.eta, updated_at = now()
            """,
            {
                "mmsi": msg.mmsi, "imo": msg.imo, "name": msg.name, "callsign": msg.callsign,
                "flag": flag_from_mmsi(msg.mmsi), "type": msg.ship_type_code,
                "length": msg.length_m, "beam": msg.beam_m,
                "size_class": cls.size_class, "cargo_group": cls.cargo_group,
                "draught": state.draught_m, "dmin": state.draught_min_m, "dmax": state.draught_max_m,
                "laden": state.laden, "dest": msg.destination, "eta": msg.eta,
            },
        )

    def add_position(self, msg: PositionMsg, draught_m: float | None) -> None:
        params = {
            "mmsi": msg.mmsi, "ts": msg.ts, "lon": msg.lon, "lat": msg.lat, "sog": msg.sog,
            "cog": msg.cog, "heading": msg.heading, "nav": msg.nav_status, "draught": draught_m,
        }
        self.conn.execute(
            """
            INSERT INTO positions (mmsi, ts, geom, sog, cog, heading, nav_status, draught_m)
            VALUES (%(mmsi)s, %(ts)s, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326),
                    %(sog)s, %(cog)s, %(heading)s, %(nav)s, %(draught)s)
            ON CONFLICT (mmsi, ts) DO NOTHING
            """,
            params,
        )
        self.conn.execute(
            """
            INSERT INTO latest_position (mmsi, ts, geom, sog, cog, heading, nav_status, updated_at)
            VALUES (%(mmsi)s, %(ts)s, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326),
                    %(sog)s, %(cog)s, %(heading)s, %(nav)s, now())
            ON CONFLICT (mmsi) DO UPDATE SET
                ts = EXCLUDED.ts, geom = EXCLUDED.geom, sog = EXCLUDED.sog, cog = EXCLUDED.cog,
                heading = EXCLUDED.heading, nav_status = EXCLUDED.nav_status, updated_at = now()
            WHERE latest_position.ts < EXCLUDED.ts
            """,
            params,
        )

    def load_tanker_states(self) -> dict[int, VesselState]:
        with self.conn.cursor(row_factory=psycopg.rows.tuple_row) as cur:
            cur.execute(
                "SELECT mmsi, size_class, length_m, draught_m, draught_min_m, draught_max_m, laden FROM vessels"
            )
            rows = cur.fetchall()
        return {r[0]: VesselState(*r) for r in rows}
