import queue
import threading
import time

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from common.database import connect, database_url
from tests.helpers import seed_vessel


@pytest.fixture
def client(db):
    app = create_app(conninfo=database_url(test=True), poll_seconds=0.05)
    with TestClient(app) as c:
        yield c


class Feeder:
    """Touch rows repeatedly from its own connection until stopped, so the test
    does not depend on when the server processed the subscription."""

    def __init__(self, statements):
        self.statements = statements
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        conn = connect(test=True)
        try:
            deadline = time.monotonic() + 15
            while not self.stop.is_set() and time.monotonic() < deadline:
                for s in self.statements:
                    conn.execute(s)
                time.sleep(0.05)
        finally:
            conn.close()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(5)


def receive(ws, timeout=10):
    """receive_json with a bounded wait (TestClient's own receive blocks forever)."""
    q = queue.Queue()
    threading.Thread(target=lambda: q.put(ws.receive_json()), daemon=True).start()
    try:
        return q.get(timeout=timeout)
    except queue.Empty:
        pytest.fail("no websocket message within timeout")


def test_vessels_endpoint_with_filters_and_bbox(client, db):
    seed_vessel(db, 1, size_class="MR", lon=10, lat=10)
    seed_vessel(db, 2, size_class="Suezmax", lon=50, lat=10)
    r = client.get("/api/vessels", params={"zoom": 8, "bbox": "0,0,20,20", "size_class": ["MR", "VLCC"]})
    assert r.status_code == 200
    assert [f["properties"]["mmsi"] for f in r.json()["features"]] == [1]


def test_bad_bbox_is_422(client):
    assert client.get("/api/vessels", params={"bbox": "1,2,3"}).status_code == 422
    assert client.get("/api/vessels", params={"bbox": "a,b,c,d"}).status_code == 422


def test_detail_404_and_ok(client, db):  # Review Focus 5
    seed_vessel(db, 1, name="ALPHA")
    assert client.get("/api/vessels/1").json()["name"] == "ALPHA"
    assert client.get("/api/vessels/999").status_code == 404


def test_track_defaults_and_404(client, db):
    seed_vessel(db, 1)
    r = client.get("/api/vessels/1/track")
    assert r.status_code == 200 and r.json()["geometry"]["type"] == "MultiLineString"
    assert client.get("/api/vessels/999/track").status_code == 404


def test_huge_mmsi_is_not_a_500(client):
    for path in ("/api/vessels/99999999999999999999", "/api/vessels/1000000000000",
                 "/api/vessels/99999999999999999999/track", "/api/vessels/1000000000000/track",
                 "/api/vessels/0", "/api/vessels/-5"):
        assert client.get(path).status_code in (404, 422), path


def test_search_and_stats_and_meta(client, db):
    seed_vessel(db, 111111111, name="NORDIC MARS")
    assert client.get("/api/search", params={"q": "mars"}).json()[0]["mmsi"] == 111111111
    assert client.get("/api/search", params={"q": ""}).json() == []                 # Review Focus 5
    assert client.get("/api/stats").json()["total"] == 1
    assert client.get("/api/meta").json()["stale_hours"] == 6


def test_hostile_filter_values_are_422_without_details(client, db):
    seed_vessel(db, 1)
    nul = chr(0)
    for params in ({"size_class": "a" + nul + "b"}, {"flag": "x" + nul}):
        for path in ("/api/vessels", "/api/stats"):
            r = client.get(path, params=params)
            assert r.status_code == 422, (path, params, r.status_code)
            assert r.json() == {"detail": "invalid filter value"}
    # out-of-range integers: handled by the filters or by the 422 handler, never a 500
    for n in (10**30, 2**40, 2**20):
        for path in ("/api/vessels", "/api/stats"):
            assert client.get(path, params={"nav_status": n}).status_code in (200, 422), (path, n)
    # the server is still healthy afterwards
    assert client.get("/api/stats").status_code == 200


def test_ws_pushes_only_matching_updates(client, db):
    seed_vessel(db, 1, lon=10, lat=10)
    seed_vessel(db, 2, lon=80, lat=10)
    with client.websocket_connect("/ws/positions") as ws:
        ws.send_json({"bbox": [0, 0, 20, 20]})
        with Feeder(["UPDATE latest_position SET updated_at = now() WHERE mmsi = 2",   # outside bbox
                     "UPDATE latest_position SET updated_at = now() WHERE mmsi = 1"]):  # inside bbox
            msg = receive(ws)
        assert msg["type"] == "positions"
        assert [f["properties"]["mmsi"] for f in msg["features"]] == [1]


def test_ws_ignores_garbage_subscription(client, db):
    seed_vessel(db, 1)
    with client.websocket_connect("/ws/positions") as ws:
        ws.send_json({"bbox": "nonsense", "nav_status": ["x"]})
        with Feeder(["UPDATE latest_position SET updated_at = now()"]):
            assert receive(ws)["type"] == "positions"


def test_ws_bad_subscription_errors_once_then_recovers(client, db):
    seed_vessel(db, 1, lon=10, lat=10)
    with client.websocket_connect("/ws/positions") as ws:
        ws.send_json({"size_class": ["a\x00b"]})
        assert receive(ws) == {"type": "error", "detail": "invalid subscription"}
        # connection survives; a good subscription now works and no second error frame appears
        ws.send_json({"bbox": [0, 0, 20, 20]})
        with Feeder(["UPDATE latest_position SET updated_at = now() WHERE mmsi = 1"]):
            msg = receive(ws)
        assert msg["type"] == "positions"
        assert [f["properties"]["mmsi"] for f in msg["features"]] == [1]
    # server still serves REST after the bad subscription
    assert client.get("/api/meta").status_code == 200
