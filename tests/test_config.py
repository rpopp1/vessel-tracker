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
