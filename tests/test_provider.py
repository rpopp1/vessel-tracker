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


async def _collect(provider, n, timeout=10):
    got = []
    async with asyncio.timeout(timeout):
        gen = provider.messages()
        async for msg in gen:
            got.append(msg)
            if len(got) == n:
                break
        await gen.aclose()
    return got


async def test_received_counts_frames_and_lifecycle_logged(caplog):
    import logging
    caplog.set_level(logging.INFO, logger="collector")

    async def handler(ws):
        await ws.recv()
        await ws.send("not json")
        await ws.send(json.dumps(POSITION_REPORT))
        await asyncio.sleep(5)

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        provider = AISStreamProvider(api_key="fake-test-key", url=f"ws://127.0.0.1:{port}", initial_delay=0.01)
        assert provider.received == 0 and provider.last_received is None
        await _collect(provider, 1)
    assert provider.received == 2 and provider.dropped == 1
    assert provider.last_received is not None
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "connected" in text and "subscription sent" in text and "first message received" in text
    assert "fake-test-key" not in text and "APIKey" not in text and "BoundingBoxes" not in text


async def test_first_drop_warned_once_per_connection(caplog):
    import logging
    caplog.set_level(logging.INFO, logger="collector")
    connections = 0

    async def handler(ws):
        nonlocal connections
        connections += 1
        await ws.recv()
        await ws.send("not json")
        await ws.send("not json again")
        await ws.send(json.dumps({"error": "boom"}))
        await ws.send(json.dumps({"MessageType": "Weird" * 20, "Message": {"x": "SECRET-BODY"}}))
        if connections == 1:
            await ws.send(json.dumps(POSITION_REPORT))
            await ws.close()
        else:
            await ws.send(json.dumps(POSITION_REPORT))
            await ws.send("not json")
            await asyncio.sleep(5)

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        provider = AISStreamProvider(api_key="fake-test-key", url=f"ws://127.0.0.1:{port}", initial_delay=0.01)
        await _collect(provider, 2)
    warns = [r.getMessage() for r in caplog.records if r.levelname == "WARNING" and "drop" in r.getMessage().lower()]
    assert len(warns) == 2                      # one per connection, later drops silent
    assert "not JSON" in warns[0]
    assert all("SECRET-BODY" not in r.getMessage() for r in caplog.records)
    assert all("fake-test-key" not in r.getMessage() for r in caplog.records)


async def test_unsupported_type_reason_is_truncated(caplog):
    import logging
    caplog.set_level(logging.INFO, logger="collector")

    async def handler(ws):
        await ws.recv()
        await ws.send(json.dumps({"MessageType": "W" * 200, "Message": {}}))
        await ws.send(json.dumps(POSITION_REPORT))
        await asyncio.sleep(5)

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        provider = AISStreamProvider(api_key="fake-test-key", url=f"ws://127.0.0.1:{port}", initial_delay=0.01)
        await _collect(provider, 1)
    warn = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"][0]
    assert "unsupported message type" in warn and "W" * 41 not in warn and "W" * 40 in warn


async def test_connect_timeout_is_explicit_and_logged_as_reconnect_warning(monkeypatch, caplog):
    import logging
    from collector.providers import aisstream
    caplog.set_level(logging.INFO, logger="collector")
    seen = {}

    def fake_connect(url, **kw):
        seen.update(kw)
        raise TimeoutError("timed out during opening handshake")

    async def handler(ws):
        await ws.recv()

    monkeypatch.setattr(aisstream, "connect", fake_connect)
    delays, got = await _run_recording_delays(monkeypatch, handler, 2)
    assert seen["open_timeout"] == 15
    warns = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("TimeoutError" in w and "reconnecting" in w for w in warns)


async def _error_frame_logs(caplog, error_value):
    import logging
    caplog.set_level(logging.INFO, logger="collector")

    async def handler(ws):
        await ws.recv()
        await ws.send(json.dumps({"error": error_value}))
        await ws.send(json.dumps({"error": "second"}))
        await ws.send(json.dumps(POSITION_REPORT))
        await asyncio.sleep(5)

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        provider = AISStreamProvider(api_key="fake-test-key", url=f"ws://127.0.0.1:{port}", initial_delay=0.01)
        await _collect(provider, 1)
    return [r for r in caplog.records if r.levelname == "ERROR"]


async def test_error_frame_text_logged_truncated_and_once(caplog):
    recs = await _error_frame_logs(caplog, "Api Key" + chr(10) + "is not valid " + "x" * 300)
    assert len(recs) == 1                                  # second error frame is sampled away
    msg = recs[0].getMessage()
    assert msg.startswith("AISstream error frame: Api Key is not valid xxx")
    assert chr(10) not in msg and len(msg) == len("AISstream error frame: ") + 160


async def test_error_frame_containing_key_is_redacted(caplog):
    recs = await _error_frame_logs(caplog, "bad key fake-test-key rejected")
    assert [r.getMessage() for r in recs] == ["AISstream error frame: bad key [redacted] rejected"]
    assert all("fake-test-key" not in r.getMessage() for r in caplog.records)


CONFIRMATION = {"Message": {"CompressionEnabled": True}, "MessageType": "SubscriptionConfirmation"}


async def test_subscription_confirmation_is_not_dropped_and_logged_once(caplog):
    import logging
    caplog.set_level(logging.INFO, logger="collector")

    async def handler(ws):
        await ws.recv()
        await ws.send(json.dumps(CONFIRMATION))
        await ws.send(json.dumps(CONFIRMATION))
        await ws.send(json.dumps(POSITION_REPORT))  # confirmations are processed before this is yielded
        await asyncio.sleep(5)

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        provider = AISStreamProvider(api_key="fake-test-key", url=f"ws://127.0.0.1:{port}", initial_delay=0.01)
        got = await _collect(provider, 1)
    assert isinstance(got[0], PositionMsg)
    assert provider.dropped == 0
    confirmed = [r for r in caplog.records if r.getMessage() == "AISstream subscription confirmed"]
    assert len(confirmed) == 1 and confirmed[0].levelname == "INFO"
    assert not [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]


async def test_unparseable_frame_before_valid_one_is_counted_as_dropped():
    async def handler(ws):
        await ws.recv()
        await ws.send(json.dumps({"MessageType": "Weird"}))
        await ws.send(json.dumps(POSITION_REPORT))
        await asyncio.sleep(5)

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        provider = AISStreamProvider(api_key="fake-test-key", url=f"ws://127.0.0.1:{port}", initial_delay=0.01)
        await _collect(provider, 1)
    assert provider.dropped == 1
