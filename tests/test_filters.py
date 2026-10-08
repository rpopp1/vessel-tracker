from api.filters import VesselFilters, build_where, filters_from_json


def test_default_filters_only_apply_stale_cutoff():
    where, params = build_where(VesselFilters(), stale_hours=6)
    assert "lp.ts >" in where and params == [6]


def test_all_filters_produce_clauses_and_params():
    f = VesselFilters(bbox=(0, 1, 2, 3), size_class=("MR",), cargo_group=("products",), laden=True,
                      flag=("Panama",), nav_status=(0, 1), min_speed=1.0, max_speed=5.0)
    where, params = build_where(f, 6)
    assert where.count("%s") == len(params)
    assert ["MR"] in params and [0, 1] in params and True in params


def test_antimeridian_bbox_uses_two_envelopes():  # Review Focus 2
    where, params = build_where(VesselFilters(bbox=(170.0, -10.0, -170.0, 10.0)), 6)
    assert where.count("ST_MakeEnvelope") == 2
    assert 170.0 in params and -170.0 in params and 180 in params and -180 in params


def test_normal_bbox_uses_one_envelope():
    where, _ = build_where(VesselFilters(bbox=(-10.0, -10.0, 10.0, 10.0)), 6)
    assert where.count("ST_MakeEnvelope") == 1


def test_skip_omits_one_dimension():
    f = VesselFilters(size_class=("MR",), cargo_group=("products",))
    where, params = build_where(f, 6, skip="size_class")
    assert "size_class" not in where and ["products"] in params and ["MR"] not in params


def test_filters_from_json_roundtrip_and_garbage():
    f = filters_from_json({"bbox": [1, 2, 3, 4], "size_class": ["MR"], "laden": False, "nav_status": ["0"]})
    assert f.bbox == (1.0, 2.0, 3.0, 4.0) and f.size_class == ("MR",) and f.laden is False and f.nav_status == (0,)
    assert filters_from_json({"bbox": [1, 2]}).bbox is None          # wrong length ignored
    assert filters_from_json({"nav_status": ["x"]}) == VesselFilters()  # unparseable -> defaults
