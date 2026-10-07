"""Bars-topic coalescer (`23-ws-protocol.md` §8.2, #2018).

Pure, bounded state: pending bar items are keyed by ``(generation, index)``
— never by ``t_ms`` (non-time bars share open times). Last write wins, except
a confirmed bar is never replaced by an unconfirmed one, and a confirmed bar
is replaced by another confirmed bar only when the incoming item sets
``amended`` (late-trade re-close, 24 §3.2).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

BarKey = tuple[int, int]
BarItem = Mapping[str, Any]


def bar_key(item: BarItem) -> BarKey:
    """Return the coalescing key; `generation` and `index` are required."""
    return (int(item["generation"]), int(item["index"]))


class BarCoalescer:
    """Accumulates bar updates between flushes; the flush keeps final state exact."""

    def __init__(self, max_pending: int = 4096) -> None:
        self._max = max_pending
        self._pending: dict[BarKey, dict[str, Any]] = {}
        self._count = 0
        self.overflowed = False

    def add(self, item: BarItem) -> None:
        key = bar_key(item)
        self._count += 1
        cur = self._pending.get(key)
        if cur is not None and cur.get("confirm"):
            if not item.get("confirm"):
                return
            if not item.get("amended"):
                return
        elif cur is None and len(self._pending) >= self._max:
            self.overflowed = True  # caller must drop pending + force re-snapshot (§8.3)
            return
        self._pending[key] = dict(item)

    def flush(self) -> tuple[list[dict[str, Any]], int]:
        """Return (items ordered by key, coalesced_count) and reset."""
        items = [self._pending[k] for k in sorted(self._pending)]
        count = self._count
        self._pending = {}
        self._count = 0
        return items, count
