"""Dedicated ping task + per-topic staleness detection (E08-T04, R6 Feed rot).

Plain code (hot-path exclusion). The ping loop is its own task and never runs
inline in the read loop, so a slow consumer cannot starve it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from candleviewer.ingestion.planner import DemandTracker

PING_INTERVAL_S = 20.0
PONG_DEADLINE_S = 10.0
STALENESS_S: dict[str, float] = {"book": 2.0, "trade": 10.0, "ticker": 5.0}


@dataclass(frozen=True, slots=True)
class FeedHealthEvent:
    topic: str
    state: str  # "stale" | "healthy" | "resubscribing" | "degraded" | "delisted"
    last_msg_age_s: float


def _default_kind(topic: str) -> str:
    """Venue-neutral fallback: the topic's first dotted segment."""
    return topic.split(".", 1)[0]


class StalenessWatchdog:
    def __init__(
        self,
        clock: Callable[[], float],
        on_health: Callable[[FeedHealthEvent], None],
        limits: dict[str, float] | None = None,
        *,
        kind_of: Callable[[str], str] | None = None,
    ) -> None:
        self._clock = clock
        # Exchange-specific topic -> stream-kind mapping is injected by the
        # composition root (C-2.2: venue vocabulary stays in exchange/<venue>/).
        self._kind = kind_of or _default_kind
        self._on_health = on_health
        self._limits = limits or STALENESS_S
        self._last: dict[str, float] = {}
        self._stale: set[str] = set()

    def watch(self, topic: str) -> None:
        self._last[topic] = self._clock()

    def unwatch(self, topic: str) -> None:
        self._last.pop(topic, None)
        self._stale.discard(topic)

    def touch(self, topic: str) -> None:
        if topic in self._last:
            self._last[topic] = self._clock()
            self._stale.discard(topic)

    def reset(self) -> None:
        """Restart staleness timers (after a reconnect)."""
        now = self._clock()
        for topic in self._last:
            self._last[topic] = now
        self._stale.clear()

    def all_stale(self) -> bool:
        """True when every watched topic that has a limit is stale (#1913): only
        then is the shared socket suspect; one silent topic is per-topic."""
        limited = {t for t in self._last if self._kind(t) in self._limits}
        return bool(limited) and limited <= self._stale

    def check(self) -> list[str]:
        """Emit stale events; returns newly stale topics."""
        now = self._clock()
        fired: list[str] = []
        for topic, last in self._last.items():
            limit = self._limits.get(self._kind(topic))
            if limit is not None and now - last >= limit and topic not in self._stale:
                self._stale.add(topic)
                fired.append(topic)
                self._on_health(FeedHealthEvent(topic, "stale", now - last))
        return fired


async def prune_unlisted(
    demand: DemandTracker,
    is_listed: Callable[[str], bool],
    sync: Callable[[], None],
    publish: Callable[[FeedHealthEvent], Awaitable[None]],
    topic_for: Callable[[str], str],
) -> list[str]:
    """#1913: drop demand for symbols the catalogue no longer lists as trading
    (held topics were only checked on `acquire`), unsubscribe via `sync()`, and
    publish a plain `delisted` FeedHealthEvent per symbol. Shared by streams."""
    gone = sorted(s for s in demand.desired() if not is_listed(s))
    for sym in gone:
        demand.drop(sym)
    if gone:
        sync()
    for sym in gone:
        await publish(FeedHealthEvent(topic_for(sym), "delisted", 0.0))
    return gone


async def ping_loop(
    send_ping: Callable[[], Awaitable[None]],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    *,
    interval_s: float = PING_INTERVAL_S,
) -> None:
    """Emit a ping every `interval_s` forever; cancel to stop."""
    while True:
        await sleep(interval_s)
        await send_ping()
