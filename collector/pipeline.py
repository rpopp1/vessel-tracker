from __future__ import annotations

from typing import Protocol

from collector.classify import Classification, classify, estimate_laden, is_tanker_type
from common.config import Config
from common.models import AISMessage, PositionMsg, StaticMsg, VesselState


class StoreLike(Protocol):
    def upsert_vessel(self, msg: StaticMsg, cls: Classification, state: VesselState) -> None: ...
    def add_position(self, msg: PositionMsg, draught_m: float | None) -> None: ...


class Pipeline:
    """Keeps only tankers. A vessel becomes known when a tanker static message arrives."""

    def __init__(self, store: StoreLike, cfg: Config, tankers: dict[int, VesselState] | None = None):
        self.store = store
        self.cfg = cfg
        self.tankers: dict[int, VesselState] = dict(tankers or {})
        self.counters = {"tanker_static": 0, "non_tanker_static": 0, "position_stored": 0, "position_unknown": 0}

    def handle(self, msg: AISMessage) -> None:
        if isinstance(msg, StaticMsg):
            self._static(msg)
        else:
            self._position(msg)

    def _static(self, msg: StaticMsg) -> None:
        if not is_tanker_type(msg.ship_type_code):
            self.tankers.pop(msg.mmsi, None)
            self.counters["non_tanker_static"] += 1
            return
        prev = self.tankers.get(msg.mmsi)
        length = msg.length_m or (prev.length_m if prev else None)
        draught = msg.draught_m or (prev.draught_m if prev else None)
        dmin = prev.draught_min_m if prev else None
        dmax = prev.draught_max_m if prev else None
        if msg.draught_m:
            dmin = msg.draught_m if dmin is None else min(dmin, msg.draught_m)
            dmax = msg.draught_m if dmax is None else max(dmax, msg.draught_m)
        cls = classify(length, self.cfg)
        state = VesselState(
            mmsi=msg.mmsi,
            size_class=cls.size_class,
            length_m=length,
            draught_m=draught,
            draught_min_m=dmin,
            draught_max_m=dmax,
            laden=estimate_laden(cls.size_class, draught, dmin, dmax, self.cfg),
        )
        self.store.upsert_vessel(msg, cls, state)
        self.tankers[msg.mmsi] = state  # only once the DB has the row
        self.counters["tanker_static"] += 1

    def _position(self, msg: PositionMsg) -> None:
        state = self.tankers.get(msg.mmsi)
        if state is None:
            self.counters["position_unknown"] += 1
            return
        self.store.add_position(msg, state.draught_m)
        self.counters["position_stored"] += 1
