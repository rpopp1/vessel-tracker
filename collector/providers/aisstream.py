from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from typing import AsyncIterator

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from collector.providers.aisstream_parse import parse_message
from common.models import AISMessage

URL = "wss://stream.aisstream.io/v0/stream"
log = logging.getLogger(__name__)


class AISStreamProvider:
    def __init__(self, api_key: str | None = None, url: str = URL, initial_delay: float = 1.0):
        key = api_key or os.environ.get("AISSTREAM_API_KEY")
        if not key:
            raise RuntimeError("AISSTREAM_API_KEY environment variable is not set")
        self._key = key
        self.url = url
        self.initial_delay = initial_delay
        self.dropped = 0

    def _subscription(self) -> dict:
        return {
            "APIKey": self._key,
            "BoundingBoxes": [[[-90, -180], [90, 180]]],
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
        }

    async def messages(self) -> AsyncIterator[AISMessage]:
        delay = self.initial_delay
        while True:
            try:
                async with connect(self.url, ping_interval=20) as ws:
                    await ws.send(json.dumps(self._subscription()))
                    delay = self.initial_delay
                    async for raw in ws:
                        try:
                            data = json.loads(raw)
                        except (ValueError, TypeError):
                            self.dropped += 1
                            continue
                        if isinstance(data, dict) and "error" in data:
                            log.error("AISstream error message: %s", data["error"])
                            self.dropped += 1
                            continue
                        msg = parse_message(data) if isinstance(data, dict) else None
                        if msg is None:
                            self.dropped += 1
                            continue
                        yield msg
            except (WebSocketException, OSError) as exc:
                log.warning("AISstream connection lost (%s); reconnecting", type(exc).__name__)
            await asyncio.sleep(delay + random.random() * delay)
            delay = min(delay * 2, 60.0)
