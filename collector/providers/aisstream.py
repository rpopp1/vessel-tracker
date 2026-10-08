from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from typing import AsyncIterator

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from collector.providers.aisstream_parse import parse_message
from common.models import AISMessage

URL = "wss://stream.aisstream.io/v0/stream"
log = logging.getLogger(__name__)

OPEN_TIMEOUT = 15.0
DROP_LOG_INTERVAL = 60.0


class AISStreamProvider:
    def __init__(self, api_key: str | None = None, url: str = URL, initial_delay: float = 1.0):
        key = api_key or os.environ.get("AISSTREAM_API_KEY")
        if not key:
            raise RuntimeError("AISSTREAM_API_KEY environment variable is not set")
        self._key = key
        self.url = url
        self.initial_delay = initial_delay
        self.dropped = 0
        self.received = 0
        self.last_received: float | None = None  # time.monotonic() of the last raw frame
        self._last_drop_log = 0.0
        self._drop_warned = False  # reset on each connection

    def _subscription(self) -> dict:
        return {
            "APIKey": self._key,
            "BoundingBoxes": [[[-90, -180], [90, 180]]],
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
        }

    def _drop(self, reason: str) -> None:
        """Count a dropped frame; warn on the first drop per connection, then at most once per interval.

        Reasons are short fixed strings (or a truncated message-type name), never message bodies.
        """
        self.dropped += 1
        now = time.monotonic()
        if not self._drop_warned or now - self._last_drop_log >= DROP_LOG_INTERVAL:
            log.warning("dropped message (total dropped=%d): %s", self.dropped, reason)
            self._drop_warned = True
            self._last_drop_log = now

    async def messages(self) -> AsyncIterator[AISMessage]:
        delay = self.initial_delay
        while True:
            try:
                async with connect(self.url, ping_interval=20, open_timeout=OPEN_TIMEOUT) as ws:
                    log.info("AISstream connected")
                    self._drop_warned = False
                    first = True
                    await ws.send(json.dumps(self._subscription()))
                    log.info("AISstream subscription sent")
                    async for raw in ws:
                        self.received += 1
                        self.last_received = time.monotonic()
                        if first:
                            log.info("AISstream first message received")
                            first = False
                        try:
                            data = json.loads(raw)
                        except (ValueError, TypeError):
                            self._drop("not JSON")
                            continue
                        if isinstance(data, dict) and "error" in data:
                            self._drop("AISstream error frame")
                            continue
                        msg = parse_message(data) if isinstance(data, dict) else None
                        if msg is None:
                            mtype = data.get("MessageType") if isinstance(data, dict) else type(data).__name__
                            self._drop("unparseable/unsupported message type: %s" % str(mtype)[:40])
                            continue
                        delay = self.initial_delay
                        yield msg
            except (WebSocketException, OSError) as exc:
                log.warning("AISstream connection lost (%s); reconnecting", type(exc).__name__)
            await asyncio.sleep(delay + random.random() * delay)
            delay = min(delay * 2, 60.0)
