from __future__ import annotations

from dataclasses import dataclass

from common.config import Config


@dataclass(frozen=True)
class Classification:
    size_class: str
    cargo_group: str


UNCLASSIFIED = Classification("Unclassified", "unknown")


def is_tanker_type(code: int | None) -> bool:
    return code is not None and 80 <= code <= 89


def classify(length_m: float | None, cfg: Config) -> Classification:
    if not length_m or length_m <= 0:
        return UNCLASSIFIED
    for c in cfg.size_classes:
        if length_m >= c.min_length_m:
            return Classification(c.name, c.cargo_group)
    return UNCLASSIFIED


def estimate_laden(
    size_class: str,
    draught_m: float | None,
    obs_min: float | None,
    obs_max: float | None,
    cfg: Config,
) -> bool | None:
    if not draught_m or draught_m <= 0:
        return None
    if obs_min is not None and obs_max is not None and obs_max - obs_min >= cfg.observed_range_min_m:
        return draught_m >= (obs_min + obs_max) / 2
    ref = next((c.laden_draught_m for c in cfg.size_classes if c.name == size_class), None)
    if ref is None:
        return None
    return draught_m >= cfg.laden_ratio * ref
