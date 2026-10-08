from __future__ import annotations

import asyncio
import logging
import math
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
    bad = HTTPException(422, "bbox must be four numbers: west,south,east,north")
    parts = raw.split(",")
    if len(parts) != 4:
        raise bad
    try:
        w, s, e, n = (float(x) for x in parts)
    except ValueError:
        raise bad
    if not all(math.isfinite(v) for v in (w, s, e, n)):
        raise bad
    if not (-180 <= w <= 180 and -180 <= e <= 180 and -90 <= s <= 90 and -90 <= n <= 90 and s <= n):
        raise bad  # west > east is fine: it means the box crosses the antimeridian
    return (w, s, e, n)


def _db_now(pool) -> datetime:
    with pool.connection() as conn:
        return conn.execute("SELECT now() AS t").fetchone()["t"]


def _poll_db(pool, f: VesselFilters, cursor: tuple[datetime, int], cfg: Config):
    with pool.connection() as conn:
        return queries.updated_since(conn, f, cursor, cfg)


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
        try:
            if start > end:
                raise HTTPException(422, "'from' must not be after 'to'")
        except TypeError:  # naive vs aware datetimes
            raise HTTPException(422, "'from' and 'to' must both include a timezone or neither")
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

    @app.websocket("/ws/positions")
    async def ws_positions(ws: WebSocket):
        await ws.accept()
        send_lock = asyncio.Lock()

        async def send(payload: dict):
            async with send_lock:
                await ws.send_json(jsonable_encoder(payload))

        # cursor starts at the DATABASE clock so app/db clock skew cannot lose or replay rows
        try:
            start_cursor = (await asyncio.to_thread(_db_now, pool), 0)
        except Exception as exc:
            log.warning("websocket start failed: %s", type(exc).__name__)
            try:
                await send({"type": "error", "detail": "service unavailable"})
                await ws.close(code=1011)
            except (WebSocketDisconnect, RuntimeError):
                pass
            return
        # gen increments whenever a subscription is installed; results of polls started under
        # an older generation are discarded (success or failure)
        state = {"filters": VesselFilters(), "cursor": start_cursor, "gen": 0,
                 "invalid_sent": False, "outage": False}

        async def reader():
            try:
                while True:
                    try:
                        data = await ws.receive_json()
                    except (WebSocketDisconnect, RuntimeError):
                        return
                    except Exception as exc:  # bad JSON (ValueError), binary frame (KeyError), ...; never BaseException
                        log.warning("websocket frame rejected: %s", type(exc).__name__)
                        await send({"type": "error", "detail": "invalid subscription"})
                        continue
                    try:
                        f = filters_from_json(data) if isinstance(data, dict) else VesselFilters()
                    except Exception as exc:
                        log.warning("websocket subscription rejected: %s", type(exc).__name__)
                        await send({"type": "error", "detail": "invalid subscription"})
                        continue
                    try:
                        cursor = (await asyncio.to_thread(_db_now, pool), 0)
                    except Exception as exc:
                        log.warning("websocket subscription failed: %s", type(exc).__name__)
                        await send({"type": "error", "detail": "service unavailable"})
                        continue  # previous subscription stays in force
                    state.update(filters=f, cursor=cursor, gen=state["gen"] + 1,
                                 invalid_sent=False, outage=False)
            except (WebSocketDisconnect, RuntimeError):
                return  # peer went away while we were sending an error frame

        task = asyncio.create_task(reader())
        try:
            while not task.done():
                await asyncio.sleep(poll_seconds)
                f, cursor, gen = state["filters"], state["cursor"], state["gen"]
                try:
                    features, new_cursor = await asyncio.to_thread(_poll_db, pool, f, cursor, cfg)
                except Exception as exc:
                    if state["gen"] != gen:
                        continue  # subscription replaced while polling: discard the failure silently
                    if isinstance(exc, (psycopg.errors.DataError, psycopg.ProgrammingError, ValueError)):
                        if not state["invalid_sent"]:  # bad subscription values: reset once
                            log.warning("websocket poll failed: %s", type(exc).__name__)
                            state["invalid_sent"] = True
                            state["filters"] = VesselFilters()
                            await send({"type": "error", "detail": "invalid subscription"})
                    elif not state["outage"]:  # transient (pool/connection): keep filters and cursor
                        log.warning("websocket poll unavailable: %s", type(exc).__name__)
                        state["outage"] = True
                        await send({"type": "error", "detail": "temporarily unavailable"})
                    continue
                if state["gen"] != gen:
                    continue  # stale result
                state["invalid_sent"] = state["outage"] = False
                if features:
                    state["cursor"] = new_cursor
                    await send({"type": "positions", "features": features})
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            task.cancel()
            await asyncio.wait([task])  # wait() never raises the task's error, nor hides our own cancellation
            if not task.cancelled():
                task.exception()  # consume it so nothing is "never retrieved"

    return app
