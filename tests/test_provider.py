import asyncio
import json

from websockets.asyncio.server import serve

from collector.providers.aisstream import AISStreamProvider
from common.models import PositionMsg, StaticMsg
from tests.samples import POSITION_REPORT, SHIP_STATIC_TANKER


async def test_subscribes_parses_ignores_errors_and_reconnects():
    subscriptions = []
    connections = 0

    async def handler(ws):
        nonlocal connections
        connections += 1
        subscriptions.append(json.loads(await ws.recv()))
        await ws.send(json.dumps({"error": "something"}))      # must be skipped, not crash
        await ws.send("not json")                              # must be skipped, not crash
        if connections == 1:
            await ws.send(json.dumps(SHIP_STATIC_TANKER))
            await ws.close()                                   # force a reconnect
        else:
            await ws.send(json.dumps(POSITION_REPORT))
            await asyncio.sleep(5)

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        provider = AISStreamProvider(api_key="fake-test-key", url=f"ws://127.0.0.1:{port}", initial_delay=0.01)
        got = []
        async with asyncio.timeout(10):
            gen = provider.messages()
            async for msg in gen:
                got.append(msg)
                if len(got) == 2:
                    break
            await gen.aclose()

    assert isinstance(got[0], StaticMsg) and isinstance(got[1], PositionMsg)
    assert connections == 2
    sub = subscriptions[0]
    assert sub["APIKey"] == "fake-test-key"
    assert sub["BoundingBoxes"] == [[[-90, -180], [90, 180]]]
    assert sorted(sub["FilterMessageTypes"]) == ["PositionReport", "ShipStaticData"]
    assert provider.dropped >= 2


def test_missing_api_key_raises(monkeypatch):
    import pytest
    monkeypatch.delenv("AISSTREAM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="AISSTREAM_API_KEY"):
        AISStreamProvider()
