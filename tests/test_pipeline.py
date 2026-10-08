from collector.pipeline import Pipeline
from common.config import load_config
from tests.samples import POSITION_REPORT, SHIP_STATIC_TANKER, with_static
from collector.providers.aisstream_parse import parse_message

CFG = load_config()


class FakeStore:
    def __init__(self):
        self.vessels, self.positions = [], []

    def upsert_vessel(self, msg, cls, state):
        self.vessels.append((msg, cls, state))

    def add_position(self, msg, draught_m):
        self.positions.append((msg, draught_m))


def make():
    store = FakeStore()
    return store, Pipeline(store, CFG)


def test_position_before_static_is_dropped():  # Review Focus 1
    store, p = make()
    p.handle(parse_message(POSITION_REPORT))
    assert store.positions == [] and p.counters["position_unknown"] == 1


def test_non_tanker_static_then_position_is_dropped():  # Review Focus 1
    store, p = make()
    p.handle(parse_message(with_static(Type=70)))
    p.handle(parse_message(POSITION_REPORT))
    assert store.vessels == [] and store.positions == []
    assert p.counters["non_tanker_static"] == 1


def test_tanker_static_then_position_is_stored_with_draught():
    store, p = make()
    p.handle(parse_message(SHIP_STATIC_TANKER))
    (_, cls, state), = store.vessels
    assert cls.size_class == "ULCC/VLCC" and state.draught_m == 19.5 and state.laden is True
    p.handle(parse_message(POSITION_REPORT))
    (pos, draught), = store.positions
    assert pos.mmsi == 636012345 and draught == 19.5


def test_later_static_updates_draught_range_and_laden():
    store, p = make()
    p.handle(parse_message(SHIP_STATIC_TANKER))                      # 19.5 m
    p.handle(parse_message(with_static(MaximumStaticDraught=9.0)))   # ballast now
    state = store.vessels[-1][2]
    assert (state.draught_min_m, state.draught_max_m) == (9.0, 19.5)
    assert state.laden is False


def test_static_without_dimensions_keeps_previous_length():
    store, p = make()
    p.handle(parse_message(SHIP_STATIC_TANKER))
    p.handle(parse_message(with_static(Dimension={"A": 0, "B": 0, "C": 0, "D": 0})))
    assert store.vessels[-1][1].size_class == "ULCC/VLCC"


def test_tanker_without_dimensions_is_unclassified():  # Review Focus 3
    store, p = make()
    p.handle(parse_message(with_static(Dimension={"A": 0, "B": 0, "C": 0, "D": 0})))
    assert store.vessels[0][1].size_class == "Unclassified"


def test_type_change_to_non_tanker_forgets_vessel():
    store, p = make()
    p.handle(parse_message(SHIP_STATIC_TANKER))
    p.handle(parse_message(with_static(Type=70)))
    p.handle(parse_message(POSITION_REPORT))
    assert store.positions == []


class FailingUpsertStore(FakeStore):
    def upsert_vessel(self, msg, cls, state):
        raise RuntimeError("db down")


def test_failed_upsert_leaves_memory_consistent():
    store = FailingUpsertStore()
    p = Pipeline(store, CFG)
    try:
        p.handle(parse_message(SHIP_STATIC_TANKER))
    except RuntimeError:
        pass
    assert 636012345 not in p.tankers
    assert p.counters["tanker_static"] == 0
    p.handle(parse_message(POSITION_REPORT))
    assert store.positions == [] and p.counters["position_unknown"] == 1
