"""`SubscriptionPlanner` + reference-counted demand (E08-T04, US-MKT-005).

Pure, I/O-free: `plan(desired)` packs topic strings into subscribe batches that
respect the per-frame topic cap and `args` character cap, and splits across
sockets when a socket's topic budget is reached. Plain code by design
(catalogue §1.2 hot-path exclusion; not a statechart).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass

MAX_TOPICS_PER_FRAME = 10
MAX_ARGS_CHARS = 21_000
DEFAULT_GRACE_S = 30.0


@dataclass(frozen=True, slots=True)
class Batch:
    socket_index: int
    topics: tuple[str, ...]


class SubscriptionPlanner:
    def __init__(
        self,
        *,
        max_topics_per_frame: int = MAX_TOPICS_PER_FRAME,
        max_args_chars: int = MAX_ARGS_CHARS,
        max_topics_per_socket: int = 500,
    ) -> None:
        if min(max_topics_per_frame, max_args_chars, max_topics_per_socket) < 1:
            raise ValueError("planner limits must be positive")
        self._per_frame = max_topics_per_frame
        self._max_chars = max_args_chars
        self._per_socket = max_topics_per_socket

    def plan(self, desired: Iterable[str]) -> list[Batch]:
        topics = sorted(set(desired))  # dedup: one upstream sub per topic
        batches: list[Batch] = []
        socket_index = 0
        socket_count = 0
        current: list[str] = []

        def flush() -> None:
            nonlocal current
            if current:
                batches.append(Batch(socket_index, tuple(current)))
                current = []

        for topic in topics:
            if len(json.dumps([topic])) > self._max_chars:
                raise ValueError(f"topic {topic!r} alone exceeds the args cap")
            if socket_count >= self._per_socket:
                flush()
                socket_index += 1
                socket_count = 0
            if len(current) >= self._per_frame or (
                current and len(json.dumps([*current, topic])) > self._max_chars
            ):
                flush()
            current.append(topic)
            socket_count += 1
        flush()
        return batches


class DemandTracker:
    """Reference-counted demand with a grace period on the last consumer."""

    def __init__(self, clock: Callable[[], float], grace_s: float = DEFAULT_GRACE_S) -> None:
        self._clock = clock
        self._grace = grace_s
        self._refs: dict[str, set[str]] = {}
        self._released_at: dict[str, float] = {}

    def acquire(self, consumer: str, topic: str) -> None:
        self._refs.setdefault(topic, set()).add(consumer)
        self._released_at.pop(topic, None)  # returning within grace: no churn

    def release(self, consumer: str, topic: str) -> None:
        holders = self._refs.get(topic)
        if holders is None:
            return
        holders.discard(consumer)
        if not holders:
            del self._refs[topic]
            self._released_at[topic] = self._clock()

    def desired(self) -> set[str]:
        """Topics to keep upstream: live demand plus topics inside grace."""
        now = self._clock()
        for topic, at in list(self._released_at.items()):
            if now - at >= self._grace:
                del self._released_at[topic]
        return set(self._refs) | set(self._released_at)
