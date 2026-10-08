from __future__ import annotations

from typing import AsyncIterator, Protocol

from common.models import AISMessage


class AISProvider(Protocol):
    """A source of normalized AIS messages. Swap implementations to change data feed."""

    def messages(self) -> AsyncIterator[AISMessage]: ...
