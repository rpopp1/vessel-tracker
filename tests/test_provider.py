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


class _StopLoop(Exception):
    pass


async def _run_recording_delays(monkeypatch, handler, sleeps_wanted):
    """Run the provider against a local server, recording backoff sleeps (jitter pinned to 0)."""
    from types import SimpleNamespace

    from collector.providers import aisstream

    delays = []

    async def fake_sleep(d):
        delays.append(d)
        if len(delays) >= sleeps_wanted:
            raise _StopLoop
        await asyncio.sleep(0)

    monkeypatch.setattr(aisstream, "asyncio", SimpleNamespace(sleep=fake_sleep))
    monkeypatch.setattr(aisstream, "random", SimpleNamespace(random=lambda: 0.0))

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        provider = AISStreamProvider(api_key="fake-test-key", url=f"ws://127.0.0.1:{port}", initial_delay=0.01)
        got = []
        try:
            async with asyncio.timeout(10):
                async for msg in provider.messages():
                    got.append(msg)
        except _StopLoop:
            pass
    return delays, got


async def test_backoff_escalates_when_server_accepts_errors_and_closes(monkeypatch):
    async def handler(ws):
        await ws.recv()
        await ws.send(json.dumps({"error": "bad key"}))
        await ws.close()

    delays, got = await _run_recording_delays(monkeypatch, handler, 4)
    assert got == []
    assert delays == [0.01, 0.02, 0.04, 0.08]


async def test_backoff_resets_after_successful_message(monkeypatch):
    connections = 0

    async def handler(ws):
        nonlocal connections
        connections += 1
        await ws.recv()
        if connections == 2:
            await ws.send(json.dumps(POSITION_REPORT))
        else:
            await ws.send(json.dumps({"error": "x"}))
        await ws.close()

    delays, got = await _run_recording_delays(monkeypatch, handler, 3)
    assert len(got) == 1
    assert delays == [0.01, 0.01, 0.02]
