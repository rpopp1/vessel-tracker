from common.config import load_config


def test_default_config_loads_sorted_largest_first():
    cfg = load_config()
    names = [c.name for c in cfg.size_classes]
    assert names[0] == "ULCC/VLCC"
    assert names[-1] == "Handy/small"
    lengths = [c.min_length_m for c in cfg.size_classes]
    assert lengths == sorted(lengths, reverse=True)
    assert cfg.stale_hours == 6
    assert cfg.fade_hours == 2


import pytest
import yaml

from common.config import DEFAULT_PATH


def _write(tmp_path, **overrides):
    raw = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))
    raw.update(overrides)
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return p


def _cls(name, length, draught=10.0):
    return {"name": name, "min_length_m": length, "cargo_group": "x", "laden_draught_m": draught}


def test_default_config_passes_validation():
    assert load_config(DEFAULT_PATH).retention_months >= 1


@pytest.mark.parametrize("overrides,match", [
    ({"retention_months": 0}, "retention_months"),
    ({"retention_months": -3}, "retention_months"),
    ({"fade_hours": 0}, "fade_hours"),
    ({"stale_hours": 0}, "stale_hours"),
    ({"stale_hours": -1}, "stale_hours"),
    ({"fade_hours": 5, "stale_hours": 4}, "stale_hours"),
    ({"size_classes": []}, "size_classes"),
    ({"size_classes": [_cls("A", 100), _cls("B", 50)]}, "min_length_m == 0"),
    ({"size_classes": [_cls("A", 100), _cls("A", 0)]}, "duplicate"),
    ({"laden_ratio": 0}, "laden_ratio"),
    ({"laden_ratio": 1.5}, "laden_ratio"),
    ({"observed_range_min_m": 0}, "observed_range_min_m"),
    ({"size_classes": [_cls("A", 100, 0), _cls("B", 0)]}, "laden_draught_m"),
])
def test_invalid_config_raises_value_error(tmp_path, overrides, match):
    with pytest.raises(ValueError, match=match):
        load_config(_write(tmp_path, **overrides))


def test_boundary_values_are_accepted(tmp_path):
    cfg = load_config(_write(tmp_path, retention_months=1, laden_ratio=1, fade_hours=3, stale_hours=3))
    assert cfg.retention_months == 1
