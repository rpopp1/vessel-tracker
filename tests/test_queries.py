from datetime import datetime, timedelta, timezone

from api import queries
from api.filters import VesselFilters
from common.config import load_config
from tests.helpers import seed_vessel

CFG = load_config()


def ids(fc):
    return sorted(f["properties"]["mmsi"] for f in fc["features"])


def test_list_filters_by_class_laden_and_hides_stale(db):  # Review Focus 4
    seed_vessel(db, 1, size_class="MR", laden=True, lon=10, lat=10)
    seed_vessel(db, 2, size_class="Suezmax", laden=False, lon=11, lat=11)
    seed_vessel(db, 3, size_class="MR", laden=True, lon=12, lat=12, age_hours=7)     # stale
    assert ids(queries.list_vessels(db, VesselFilters(), 8, CFG)) == [1, 2]
    assert ids(queries.list_vessels(db, VesselFilters(size_class=("MR",)), 8, CFG)) == [1]
    assert ids(queries.list_vessels(db, VesselFilters(laden=False), 8, CFG)) == [2]


def test_bbox_including_antimeridian(db):  # Review Focus 2
    seed_vessel(db, 1, lon=175, lat=0)
    seed_vessel(db, 2, lon=-175, lat=0)
    seed_vessel(db, 3, lon=0, lat=0)
    fc = queries.list_vessels(db, VesselFilters(bbox=(170, -10, -170, 10)), 8, CFG)
    assert ids(fc) == [1, 2]


def test_zoomed_out_returns_clusters(db):
    for i in range(5):
        seed_vessel(db, 10 + i, lon=10.0 + i * 0.01, lat=10.0)
    fc = queries.list_vessels(db, VesselFilters(), 2, CFG)
    assert len(fc["features"]) == 1
    assert fc["features"][0]["properties"] == {"cluster": True, "count": 5}


def test_detail_and_404_shape(db):
    seed_vessel(db, 1, name="ALPHA", imo=1234567, lon=1, lat=2)
    d = queries.vessel_detail(db, 1)
    assert d["name"] == "ALPHA" and d["position"]["lon"] == 1 and d["inferred"] == {"cargo_group": True, "laden": True}
    assert queries.vessel_detail(db, 999) is None


def test_stale_vessel_detail_and_track_still_available(db):  # Review Focus 4
    seed_vessel(db, 1, age_hours=48)
    now = datetime.now(timezone.utc)
    db.execute("INSERT INTO positions (mmsi, ts, geom) VALUES (1, %s, ST_SetSRID(ST_MakePoint(1,1),4326)), "
               "(1, %s, ST_SetSRID(ST_MakePoint(2,1),4326))", (now - timedelta(hours=49), now - timedelta(hours=48)))
    assert queries.vessel_detail(db, 1) is not None
    tr = queries.vessel_track(db, 1, now - timedelta(days=3), now)
    assert tr["properties"]["point_count"] == 2


def test_stats_are_faceted(db):
    seed_vessel(db, 1, size_class="MR", cargo_group="products", laden=True)
    seed_vessel(db, 2, size_class="MR", cargo_group="products", laden=False)
    seed_vessel(db, 3, size_class="Suezmax", cargo_group="mostly_crude", laden=True)
    s = queries.stats(db, VesselFilters(size_class=("MR",)), CFG)
    assert s["total"] == 2
    assert s["size_class"] == {"MR": 2, "Suezmax": 1}      # own dimension ignores its own filter
    assert s["laden"] == {"laden": 1, "ballast": 1}        # other dimensions respect it
    assert s["newest_ts"] is not None


def test_search(db):  # Review Focus 5
    seed_vessel(db, 111111111, name="NORDIC MARS", imo=9000001)
    seed_vessel(db, 222222222, name="100% STAR_X")
    assert [r["mmsi"] for r in queries.search(db, "mars")] == [111111111]
    assert [r["mmsi"] for r in queries.search(db, "9000001")] == [111111111]
    assert [r["mmsi"] for r in queries.search(db, "111111111")] == [111111111]
    assert [r["mmsi"] for r in queries.search(db, "100%")] == [222222222]   # wildcard is literal
    assert queries.search(db, "%%") == []                                      # not a match-all
    assert queries.search(db, "a") == [] and queries.search(db, "") == []
    assert queries.search(db, "9" * 40) == []                                  # absurd digit string


def test_updated_since_returns_only_newer(db):
    seed_vessel(db, 1, lon=1, lat=1)
    t0 = datetime.now(timezone.utc)
    assert queries.updated_since(db, VesselFilters(), t0, CFG)[0] == []
    db.execute("UPDATE latest_position SET updated_at = now()")
    feats, newest = queries.updated_since(db, VesselFilters(), t0, CFG)
    assert [f["properties"]["mmsi"] for f in feats] == [1] and newest > t0


def test_split_antimeridian_and_downsample():  # Review Focus 2
    lines = queries.split_antimeridian([[170, 0], [179, 0], [-179, 0], [-170, 0]])
    assert lines == [[[170, 0], [179, 0]], [[-179, 0], [-170, 0]]]
    pts = list(range(5000))
    out = queries.downsample(pts, 1000)
    assert len(out) <= 1001 and out[0] == 0 and out[-1] == 4999
    assert queries.downsample([1, 2, 3], 1000) == [1, 2, 3]


def test_meta_lists_classes_in_order():
    m = queries.meta(CFG)
    assert [c["name"] for c in m["size_classes"]][0] == "ULCC/VLCC"
    assert m["size_classes"][-1]["name"] == "Unclassified"
    assert (m["fade_hours"], m["stale_hours"]) == (2, 6)
