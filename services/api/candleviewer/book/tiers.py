"""Atomic depth-tier change (E08-S05 "Depth tier change").

The new tier is built muted to LIVE in parallel with the active one; only
then is the active engine swapped and the new tier's full snapshot published.
Consumers therefore never see deltas from both tiers interleaved, nor a
partially-built book.
"""

from __future__ import annotations

from collections.abc import Callable

from candleviewer.book.models import BookPhase
from candleviewer.book.resync import BookEngine
from candleviewer.exchange.base.models import BookDelta, BookSnapshot

#: E08-K01 decision: default heatmap/DOM tier.
DEFAULT_DEPTH = 200


class TieredBook:
    def __init__(self, make_engine: Callable[[int, bool], BookEngine], depth: int = DEFAULT_DEPTH):
        self._make = make_engine
        self.active: BookEngine = make_engine(depth, False)
        self.warming: BookEngine | None = None

    async def start(self) -> None:
        await self.active.start()

    async def change_depth(self, depth: int) -> None:
        if depth == self.active.depth:
            return
        self.warming = self._make(depth, True)
        await self.warming.start()

    async def on_event(self, ev: BookSnapshot | BookDelta) -> None:
        if ev.depth == self.active.depth:
            await self.active.on_event(ev)
            return
        w = self.warming
        if w is None or ev.depth != w.depth:
            return  # stale event from a retired tier: never published
        await w.on_event(ev)
        if w.phase is BookPhase.LIVE:
            self.active, self.warming = w, None
            w.muted = False
            await w.publish_current("resync")
