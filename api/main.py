from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import psycopg.errors
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from api import queries
from api.filters import VesselFilters, filters_from_json
from common.config import Config, load_config
from common.database import database_url

log = logging.getLogger(__name__)

MAX_MMSI = 10**12  # far below bigint; real MMSIs are 9 digits


def _parse_bbox(raw: str | None):
    if not raw:
        return None
    try:
        w, s, e, n = (float(x) for x in raw.split(","))
    except ValueError:
        raise HTTPException(422, "bbox must be four numbers: west,south,east,north")
    return (w, s, e, n)


def create_app(conninfo: str | None = None, cfg: Config | None = None, poll_seconds: float = 2.0) -> FastAPI:
    cfg = cfg or load_config()
    pool = ConnectionPool(
        conninfo or database_url(),
        kwargs={"row_factory": dict_row, "autocommit": True},
        min_size=1,
        max_size=8,
        open=False,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pool.open()
        yield
        pool.close()

    app = FastAPI(title="Vessel Tracker", lifespan=lifespan)

    @app.exception_handler(psycopg.errors.DataError)
    async def _bad_filter_value(request: Request, exc: psycopg.errors.DataError):
        # fixed message: never echo SQL, parameters or connection details
        return JSONResponse({"detail": "invalid filter value"}, status_code=422)

    def get_conn():
        with pool.connection() as conn:
            yield conn

    def filters_dep(
        bbox: str | None = None,
        size_class: list[str] = Query(default=[]),
        cargo_group: list[str] = Query(default=[]),
        laden: bool | None = None,
        flag: list[str] = Query(default=[]),
        nav_status: list[int] = Query(default=[]),
        min_speed: float | None = None,
        max_speed: float | None = None,
    ) -> VesselFilters:
        return VesselFilters(
            bbox=_parse_bbox(bbox), size_class=tuple(size_class), cargo_group=tuple(cargo_group), laden=laden,
            flag=tuple(flag), nav_status=tuple(nav_status), min_speed=min_speed, max_speed=max_speed,
        )

    @app.get("/api/vessels")
    def vessels(zoom: int | None = None, f: VesselFilters = Depends(filters_dep), conn=Depends(get_conn)):
        return queries.list_vessels(conn, f, zoom, cfg)

    @app.get("/api/vessels/{mmsi}")
    def vessel(mmsi: int = Path(gt=0, lt=MAX_MMSI), conn=Depends(get_conn)):
        d = queries.vessel_detail(conn, mmsi)
        if d is None:
            raise HTTPException(404, "vessel not found")
        return d

    @app.get("/api/vessels/{mmsi}/track")
    def track(mmsi: int = Path(gt=0, lt=MAX_MMSI), start: datetime | None = Query(default=None, alias="from"),
              end: datetime | None = Query(default=None, alias="to"), conn=Depends(get_conn)):
        if queries.vessel_detail(conn, mmsi) is None:
            raise HTTPException(404, "vessel not found")
        end = end or datetime.now(timezone.utc)
        start = start or end - timedelta(hours=24)
        return queries.vessel_track(conn, mmsi, start, end)

    @app.get("/api/search")
    def search(q: str = "", conn=Depends(get_conn)):
        return queries.search(conn, q)

    @app.get("/api/stats")
    def stats(f: VesselFilters = Depends(filters_dep), conn=Depends(get_conn)):
        return queries.stats(conn, f, cfg)

    @app.get("/api/meta")
    def meta():
        return queries.meta(cfg)

    def _db_now() -> datetime:
        with pool.connection() as conn:
            return conn.execute("SELECT now() AS t").fetchone()["t"]

    def _poll(f: VesselFilters, cursor: tuple[datetime, int]):
        with pool.connection() as conn:
            return queries.updated_since(conn, f, cursor, cfg)

    @app.websocket("/ws/positions")
    async def ws_positions(ws: WebSocket):
        await ws.accept()
        # cursor starts at the DATABASE clock so app/db clock skew cannot lose or replay rows
        state = {"filters": VesselFilters(), "cursor": (await asyncio.to_thread(_db_now), 0), "errored": False}

        async def reader():
            try:
                while True:
                    data = await ws.receive_json()
                    f = filters_from_json(data) if isinstance(data, dict) else VesselFilters()
                    cursor = (await asyncio.to_thread(_db_now), 0)
                    state["filters"], state["cursor"], state["errored"] = f, cursor, False
            except (WebSocketDisconnect, RuntimeError, ValueError):
                return

        task = asyncio.create_task(reader())
        try:
            while not task.done():
                await asyncio.sleep(poll_seconds)
                f, cursor = state["filters"], state["cursor"]
                try:
                    features, new_cursor = await asyncio.to_thread(_poll, f, cursor)
                except Exception as exc:  # bad subscription must not kill the connection
                    if not state["errored"]:
                        log.warning("websocket poll failed: %s", type(exc).__name__)
                        state["errored"] = True
                        state["filters"] = VesselFilters()
                        await ws.send_json({"type": "error", "detail": "invalid subscription"})
                    continue
                state["errored"] = False
                if state["cursor"] is not cursor:  # subscription changed while polling; drop stale result
                    continue
                if features:
                    state["cursor"] = new_cursor
                    await ws.send_json(jsonable_encoder({"type": "positions", "features": features}))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            task.cancel()

    return app
