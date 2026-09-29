"""`AuditWal` edge cases and writer failure paths not hit by the
behavioural tests: blank lines, compaction no-op, compaction reclaiming
space on a full WAL, and the flusher-death log."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from audit_fakes import FakeAuditRepository, FakeClock

from candleviewer.audit.wal import AuditWal, AuditWalFull
from candleviewer.audit.writer import AuditWriter, _log_task_failure


def test_wal_replay_skips_blank_lines(tmp_path: Path) -> None:
    wal = AuditWal(tmp_path / "w.wal")
    wal.append({"a": 1})
    with open(tmp_path / "w.wal", "ab") as fh:
        fh.write(b"\n")
    end = wal.append({"a": 2})
    assert [r for _, r in wal.replay()] == [{"a": 1}, {"a": 2}]
    assert wal.read_pending(1) == [(len(b'{"a":1}\n'), {"a": 1})]
    wal.mark_committed(end)
    assert list(wal.replay()) == []


def test_wal_compact_noop_when_nothing_committed(tmp_path: Path) -> None:
    wal = AuditWal(tmp_path / "w.wal")
    wal.append({"a": 1})
    wal.compact()
    assert [r for _, r in wal.replay()] == [{"a": 1}]


def test_wal_full_raises(tmp_path: Path) -> None:
    wal = AuditWal(tmp_path / "w.wal", max_bytes=10)
    with pytest.raises(AuditWalFull):
        wal.append({"payload": "x" * 20})


async def test_writer_compacts_committed_prefix_when_wal_full(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    w = AuditWriter(repo, str(tmp_path / "a.wal"), clock=clock, max_wal_bytes=2000)
    w._running = True  # drive the WAL by hand: no flusher task
    await w.emit("auth.login", actor_label="0", reason="r" * 400)
    first_end = w._wal.read_pending(1)[0][0]
    assert 2 * first_end <= 2000 < 3 * first_end, first_end
    w._wal.mark_committed(first_end)  # pretend it reached Postgres
    for i in range(1, 3):
        await w.emit("auth.login", actor_label=str(i), reason="r" * 400)
    assert [r["actor_label"] for _, r in w._wal.replay()] == ["1", "2"]
    assert w.refused_total == 0


async def test_log_task_failure_reports_crash(caplog: pytest.LogCaptureFixture) -> None:
    async def boom() -> None:
        raise ValueError("x")

    task = asyncio.create_task(boom())
    with pytest.raises(ValueError):
        await task
    with caplog.at_level(logging.CRITICAL):
        _log_task_failure(task)
    assert "audit writer task died" in caplog.text
