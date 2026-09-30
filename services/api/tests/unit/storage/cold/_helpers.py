"""Shared helpers for the cold-tier unit tests (in-memory hot source, clock)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pyarrow as pa

from candleviewer.storage.cold.observability import Severity
from candleviewer.storage.models import StreamKind, TimeRange

DAY_START_US = int(datetime(2026, 10, 17, tzinfo=UTC).timestamp() * 1_000_000)


def fixed_clock() -> datetime:
    return datetime(2026, 10, 18, 2, 15, tzinfo=UTC)


def day_range() -> TimeRange:
    return TimeRange(start_us=DAY_START_US, end_us=DAY_START_US + 86_400_000_000)


def trades_table(n: int, symbol: str = "BTCUSDT", start_us: int = DAY_START_US) -> pa.Table:
    return pa.table(
        {
            "ts": pa.array([start_us + i for i in range(n)], type=pa.int64()),
            "symbol": pa.array([symbol] * n, type=pa.string()),
            "price": pa.array([65000.0 + (i % 7) for i in range(n)], type=pa.float64()),
            "size": pa.array([0.01] * n, type=pa.float64()),
            "notional": pa.array([650.0] * n, type=pa.float64()),
            "side": pa.array(["Buy" if i % 2 else "Sell" for i in range(n)], type=pa.string()),
        }
    )


class SimulatedKill(BaseException):
    """Not an `Exception`, so no handler in the code under test swallows it."""


class FakeHotSource:
    """In-memory `HotTierSource`; `extra_columns` simulates hot-tier drift,
    `count_override` a source/export mismatch, `fail_after_batches` a crash."""

    def __init__(
        self,
        table: pa.Table,
        *,
        count_override: int | None = None,
        fail_after_batches: int | None = None,
    ) -> None:
        self.table = table
        self.count_override = count_override
        self.fail_after_batches = fail_after_batches
        self.reads = 0

    async def iter_partition(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, batch_rows: int
    ) -> AsyncIterator[pa.Table]:
        self.reads += 1
        for i, start in enumerate(range(0, self.table.num_rows, batch_rows)):
            if self.fail_after_batches is not None and i >= self.fail_after_batches:
                raise SimulatedKill("simulated SIGKILL mid-write")
            yield self.table.slice(start, batch_rows)

    async def count_partition(self, symbol: str, stream: StreamKind, rng: TimeRange) -> int:
        if self.count_override is not None:
            return self.count_override
        return self.table.num_rows


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[Severity, str, dict[str, str | int]]] = []

    async def emit(self, severity: Severity, code: str, detail: dict[str, str | int]) -> None:
        self.events.append((severity, code, detail))
