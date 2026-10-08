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
    return Config(
        size_classes=tuple(classes),
        laden_ratio=float(raw["laden_ratio"]),
        observed_range_min_m=float(raw["observed_range_min_m"]),
        fade_hours=float(raw["fade_hours"]),
        stale_hours=float(raw["stale_hours"]),
        retention_months=int(raw["retention_months"]),
    )
