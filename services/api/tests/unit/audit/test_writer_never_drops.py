"""Property (PR #1561 finding 1): under any interleaving of Postgres outages
and a tiny WAL flush batch, every record `emit()` accepted reaches the DB
exactly once and in order; nothing is dropped."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from audit_fakes import FakeAuditRepository, FakeClock
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditWriter


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
    asyncio.run(_scenario(n, batch, outages))
