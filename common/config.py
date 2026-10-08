from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "classification.yaml"


@dataclass(frozen=True)
class SizeClass:
    name: str
    min_length_m: float
    cargo_group: str
    laden_draught_m: float


@dataclass(frozen=True)
class Config:
    size_classes: tuple[SizeClass, ...]
    laden_ratio: float
    observed_range_min_m: float
    fade_hours: float
    stale_hours: float
    retention_months: int


def load_config(path: Path | str | None = None) -> Config:
    raw = yaml.safe_load(Path(path or DEFAULT_PATH).read_text(encoding="utf-8"))
    classes = sorted((SizeClass(**c) for c in raw["size_classes"]), key=lambda c: -c.min_length_m)
    cfg = Config(
        size_classes=tuple(classes),
        laden_ratio=float(raw["laden_ratio"]),
        observed_range_min_m=float(raw["observed_range_min_m"]),
        fade_hours=float(raw["fade_hours"]),
        stale_hours=float(raw["stale_hours"]),
        retention_months=int(raw["retention_months"]),
    )
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    """Reject values that would misbehave silently (e.g. retention_months <= 0 makes db.prune drop the current month)."""
    if cfg.retention_months < 1:
        raise ValueError(f"retention_months must be >= 1 (got {cfg.retention_months})")
    if cfg.fade_hours <= 0:
        raise ValueError(f"fade_hours must be > 0 (got {cfg.fade_hours})")
    if cfg.stale_hours <= 0:
        raise ValueError(f"stale_hours must be > 0 (got {cfg.stale_hours})")
    if cfg.stale_hours < cfg.fade_hours:
        raise ValueError(f"stale_hours ({cfg.stale_hours}) must be >= fade_hours ({cfg.fade_hours})")
    if not cfg.size_classes:
        raise ValueError("size_classes must not be empty")
    names = [c.name for c in cfg.size_classes]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"duplicate size class names: {', '.join(dupes)}")
    if cfg.size_classes[-1].min_length_m != 0:
        raise ValueError("the smallest size class must have min_length_m == 0 (catch-all)")
    for c in cfg.size_classes:
        if c.laden_draught_m <= 0:
            raise ValueError(f"size class {c.name!r}: laden_draught_m must be > 0 (got {c.laden_draught_m})")
    if not 0 < cfg.laden_ratio <= 1:
        raise ValueError(f"laden_ratio must be in (0, 1] (got {cfg.laden_ratio})")
    if cfg.observed_range_min_m <= 0:
        raise ValueError(f"observed_range_min_m must be > 0 (got {cfg.observed_range_min_m})")
