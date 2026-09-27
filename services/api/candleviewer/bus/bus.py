"""In-process topic bus (M5) — `docs/plan/20-architecture.md` §3/§4.

`Bus.publish(topic, event)` fans out synchronously to the pre-resolved
subscriber list for that topic (hot path: no string matching, O(number of
subscribers of that topic)). `Bus.subscribe(pattern, policy)` returns a
`Subscription` wrapping a bounded `asyncio.Queue` governed by one of the
three `QueuePolicy` values.

Ordering guarantee: single producer per topic (callers must not publish the
same topic concurrently from two tasks) plus FIFO delivery per subscriber
queue gives deterministic per-topic, per-subscriber ordering.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from candleviewer.bus.errors import BusShuttingDownError
from candleviewer.bus.metrics import (
    bus_conflated_total,
    bus_delivered_total,
    bus_published_total,
    bus_stream_invalidated_total,
    bus_subscriber_lag,
    ingest_queue_full_total,
)
from candleviewer.bus.models import QueuePolicy, StreamInvalidated, Topic, TopicPattern

logger = logging.getLogger("candleviewer.bus")

DEFAULT_QUEUE_SIZE = 4096
DEFAULT_LAG_WARN_THRESHOLD = 512
"""Queue depth at which a slow-consumer warning is logged (configurable per
subscription via `Bus.subscribe(..., lag_warn_threshold=...)`)."""


@dataclass
class Subscription:
    """One subscriber's queue plus its policy and bookkeeping."""

    name: str
    pattern: TopicPattern
    policy: QueuePolicy
    queue: asyncio.Queue[Any]
    maxsize: int
    lag_warn_threshold: int
    _high_water: int = field(default=0, init=False)

    async def get(self) -> Any:
        """Await the next item. For `CONFLATE_LATEST` subscribers the bus
        already collapses the queue down to the newest item on delivery
        (see `Bus._deliver`), so this is a plain queue `get`."""
        item = await self.queue.get()
        self.queue.task_done()
        return item

    def get_nowait(self) -> Any:
        item = self.queue.get_nowait()
        self.queue.task_done()
        return item

    def qsize(self) -> int:
        return self.queue.qsize()


class Bus:
    """The in-process pub/sub bus (M5). One instance per process, injected
    into `AppContext` and every module that needs to publish or subscribe."""

    def __init__(self) -> None:
        self._subscriptions: list[Subscription] = []
        self._resolved_cache: dict[str, list[Subscription]] = {}
        self._accepting = True
        self._pending_never_drop = 0

    def subscribe(
        self,
        name: str,
        pattern: str | TopicPattern,
        policy: QueuePolicy,
        *,
        maxsize: int = DEFAULT_QUEUE_SIZE,
        lag_warn_threshold: int = DEFAULT_LAG_WARN_THRESHOLD,
    ) -> Subscription:
        """Register a subscriber. `pattern` may be a dotted string (parsed via
        `TopicPattern.parse`) or a `TopicPattern`. Must be called before the
        matching topics are published so the resolved-subscriber cache for
        those topics is correct (subscriptions are not expected to churn on
        the hot path)."""
        if isinstance(pattern, str):
            pattern = TopicPattern.parse(pattern)
        sub = Subscription(
            name=name,
            pattern=pattern,
            policy=policy,
            queue=asyncio.Queue(maxsize=maxsize),
            maxsize=maxsize,
            lag_warn_threshold=lag_warn_threshold,
        )
        self._subscriptions.append(sub)
        self._resolved_cache.clear()
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subscriptions.remove(sub)
        self._resolved_cache.clear()

    def _resolve(self, topic: Topic) -> list[Subscription]:
        cached = self._resolved_cache.get(topic.key)
        if cached is not None:
            return cached
        matched = [s for s in self._subscriptions if s.pattern.matches(topic)]
        self._resolved_cache[topic.key] = matched
        return matched

    async def publish(self, topic: Topic, event: Any) -> None:
        """Fan out `event` to every subscriber whose pattern matches `topic`,
        per each subscriber's own `QueuePolicy`. The only await point is a
        full `NEVER_DROP` queue (§4.1 rule 1: bus is otherwise synchronous)."""
        if not self._accepting:
            raise BusShuttingDownError("Bus.drain() has stopped accepting publishes")
        bus_published_total.labels(topic_class=topic.topic_class).inc()
        for sub in self._resolve(topic):
            await self._deliver(sub, topic, event)

    async def _deliver(self, sub: Subscription, topic: Topic, event: Any) -> None:
        if sub.policy is QueuePolicy.NEVER_DROP:
            if sub.queue.full():
                ingest_queue_full_total.labels(**{"class": topic.topic_class}).inc()
                self._pending_never_drop += 1
                try:
                    await sub.queue.put(event)
                finally:
                    self._pending_never_drop -= 1
            else:
                await sub.queue.put(event)
        elif sub.policy is QueuePolicy.INVALIDATE_ON_FULL:
            if sub.queue.full():
                self._drain_queue_nowait(sub.queue)
                marker = StreamInvalidated(topic=topic.key, ts_event=getattr(event, "ts_event", 0))
                sub.queue.put_nowait(marker)
                bus_stream_invalidated_total.labels(topic_class=topic.topic_class).inc()
            else:
                sub.queue.put_nowait(event)
        elif sub.policy is QueuePolicy.CONFLATE_LATEST:
            # Keep newest only: drop whatever is already queued (0 or more
            # items), regardless of whether the queue happens to be full,
            # so a paused subscriber never accumulates stale backlog.
            drained = self._drain_queue_nowait(sub.queue)
            if drained:
                bus_conflated_total.labels(topic_class=topic.topic_class).inc()
            sub.queue.put_nowait(event)
        else:  # pragma: no cover - exhaustive enum guarded by mypy
            raise AssertionError(f"unhandled policy {sub.policy!r}")

        bus_delivered_total.labels(subscriber=sub.name).inc()
        depth = sub.qsize()
        if depth > sub._high_water:
            sub._high_water = depth
        bus_subscriber_lag.labels(subscriber=sub.name).set(depth)
        if depth >= sub.lag_warn_threshold:
            logger.warning(
                "bus subscriber lagging",
                extra={"subscriber": sub.name, "topic": topic.key, "queue_depth": depth},
            )

    @staticmethod
    def _drain_queue_nowait(queue: asyncio.Queue[Any]) -> int:
        """Drain and discard every currently-queued item. Returns the count
        of items removed."""
        drained: deque[Any] = deque()
        while True:
            try:
                drained.append(queue.get_nowait())
                queue.task_done()
            except asyncio.QueueEmpty:
                break
        return len(drained)

    async def drain(self, grace_s: float) -> dict[str, int]:
        """Stop accepting new publishes, then wait up to `grace_s` seconds
        for every `NEVER_DROP` subscriber queue to empty. Returns the
        outstanding item count per subscriber name that did not drain in
        time (empty dict means nothing was lost)."""
        self._accepting = False
        never_drop = [s for s in self._subscriptions if s.policy is QueuePolicy.NEVER_DROP]
        deadline = asyncio.get_event_loop().time() + grace_s
        outstanding: dict[str, int] = {}
        for sub in never_drop:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                if sub.qsize() or self._pending_never_drop:
                    outstanding[sub.name] = sub.qsize()
                continue
            try:
                await asyncio.wait_for(sub.queue.join(), timeout=max(remaining, 0))
            except TimeoutError:
                pass
            if sub.qsize():
                outstanding[sub.name] = sub.qsize()
        if outstanding:
            logger.warning("bus drain: outstanding never-drop events", extra=outstanding)
        return outstanding
