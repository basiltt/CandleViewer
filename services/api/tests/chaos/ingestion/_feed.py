"""Corpus feeder: recorded frames re-timed onto the virtual clock (E08-T05 corpus).

Only the envelope `ts`/`cts` and per-print `T` are rewritten (and, for a
symbol the corpus does not carry, `s` + topic) - every other byte keeps the
recorded shape, so the production parsers see real payloads (C-13.5).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from tests._corpus import frames
from tests.chaos.ingestion._clock import ScenarioTimeoutError
from tests.chaos.ingestion._stub_exchange import StubExchange

TICK_S = 0.1  # depth-200 book cadence (06 §6.1)
TRADE_EVERY = 5  # one trade frame per 0.5 s keeps the 10 s staleness limit far away

_BOOKS = {"BTCUSDT": "ws/orderbook_BTCUSDT.jsonl"}
_TRADES = {
    "BTCUSDT": "ws/clean_publicTrade_BTCUSDT.jsonl",
    "ETHUSDT": "ws/clean_publicTrade_ETHUSDT.jsonl",
    "SOLUSDT": "ws/clean_publicTrade_SOLUSDT.jsonl",
}
_HOLE_AT = 2700  # first u-hole in the BTC book corpus (documented in its manifest)


def retime(frame: str, ts_ms: int, *, symbol: str | None = None) -> str:
    msg: dict[str, Any] = json.loads(frame)
    msg["ts"] = ts_ms
    if "cts" in msg:
        msg["cts"] = ts_ms - 3
    data = msg.get("data")
    if symbol is not None:
        head = str(msg["topic"]).rsplit(".", 1)[0]
        msg["topic"] = f"{head}.{symbol}"
    if isinstance(data, list):
        for rec in data:
            rec["T"] = ts_ms - 5
            if symbol is not None:
                rec["s"] = symbol
    elif isinstance(data, dict) and symbol is not None:
        data["s"] = symbol
    return json.dumps(msg, separators=(",", ":"))


class Feeder:
    """Emits one book frame per tick and one trade frame every `TRADE_EVERY` ticks."""

    def __init__(
        self,
        ex: StubExchange,
        *,
        books: tuple[str, ...] = ("BTCUSDT",),
        trades: dict[str, str] | None = None,
    ) -> None:
        self.ex = ex
        self.books = {s: frames(_BOOKS[s])[:_HOLE_AT] for s in books}
        #: symbol -> corpus symbol whose recorded prints it replays
        src = trades if trades is not None else {s: s for s in books}
        self.trades = {s: (frames(_TRADES[c]), s if s != c else None) for s, c in src.items()}
        self.i = 0
        self.paused: set[str] = set()

    def _now_ms(self) -> int:
        return int(self.ex.clock.wall_s() * 1000)

    def step(self) -> None:
        now = self._now_ms()
        for sym, fs in self.books.items():
            if sym not in self.paused and self.i < len(fs):
                self.ex.emit(retime(fs[self.i], now))
        if self.i % TRADE_EVERY == 0:
            k = self.i // TRADE_EVERY
            for sym, (fs, rename) in self.trades.items():
                if sym not in self.paused:
                    self.ex.emit(retime(fs[k % len(fs)], now, symbol=rename))
        self.i += 1

    async def run(self, seconds: float) -> None:
        for _ in range(round(seconds / TICK_S)):
            self.step()
            await self.ex.clock.advance(TICK_S)

    async def run_while(self, task: asyncio.Future[Any], *, within_s: float) -> None:
        """Keep the venue publishing until `task` finishes (REST retries in flight)."""
        start = self.ex.clock.now
        while not task.done():
            if self.ex.clock.now - start > within_s:
                raise ScenarioTimeoutError(f"task not done within {within_s}s (SLO)")
            self.step()
            await self.ex.clock.advance(TICK_S)
