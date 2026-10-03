"""Property (PR #1561 finding 1): under any interleaving of Postgres outages
and a tiny WAL flush batch, every record `emit()` accepted reaches the DB
exactly once and in order; nothing is dropped."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

from audit_fakes import FakeAuditRepository, FakeClock
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditWriter


async def _inline_to_thread(fn: Callable[..., Any], /, *args: Any) -> Any:
    """Run the (in-memory) WAL call inline: no thread-pool scheduling."""
    return fn(*args)


class _MemWal:
    """In-memory stand-in for `AuditWal` (same interface/offset semantics).
    Disk durability is covered by the WAL's own tests; this property is about
    the writer's ordering/no-drop logic, and real file I/O is load-dependent."""

    def __init__(self, _path: Path, max_bytes: int = 0) -> None:
        self._frames: list[dict[str, Any]] = []  # offset == index + 1
        self._committed = 0

    def append(self, record: dict[str, Any]) -> int:
        self._frames.append(record)
        return len(self._frames)

    def committed_offset(self) -> int:
        return self._committed

    def mark_committed(self, offset: int) -> None:
        self._committed = offset

    def read_pending(self, max_records: int) -> list[tuple[int, dict[str, Any]]]:
        pending = [(i + 1, r) for i, r in enumerate(self._frames) if i + 1 > self._committed]
        return pending[:max_records]

    def compact(self) -> None:
        return None


async def _scenario(n: int, batch: int, outages: list[bool]) -> None:
    repo = FakeAuditRepository()
    with tempfile.TemporaryDirectory() as tmp:
        w = AuditWriter(
            repo,
            str(Path(tmp) / "a.wal"),
            flush_batch_size=batch,
            clock=FakeClock(),
            sleep=repo.retry_sleep,
        )
        await w.start()
        for i in range(n):
            repo.down = outages[i % len(outages)]
            await w.emit("orders.submit", actor_label="bot", object_id=str(i))
            await asyncio.sleep(0)
        repo.down = False
        await w.flush(10)
        await w.stop(1)
    assert [r["object_id"] for r in repo.rows] == [str(i) for i in range(n)]
    assert (await AuditQueryService(repo).verify()).verified


@settings(max_examples=25, deadline=None)
@given(
    n=st.integers(min_value=1, max_value=60),
    batch=st.integers(min_value=1, max_value=3),
    outages=st.lists(st.booleans(), min_size=1, max_size=8),
)
def test_writer_overflow_never_loses_a_record(n: int, batch: int, outages: list[bool]) -> None:
    with (
        mock.patch("candleviewer.audit.writer.AuditWal", _MemWal),
        mock.patch("candleviewer.audit.writer.asyncio.to_thread", _inline_to_thread),
    ):
        asyncio.run(_scenario(n, batch, outages))
