"""AuditWriter: chain continuity, redaction before persistence, outage
durability (WAL replay in order, no duplicates), lifecycle errors."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from audit_fakes import GENESIS, FakeAuditRepository, FakeClock

from candleviewer.audit.actions import UnknownAuditAction
from candleviewer.audit.models import ExchangeEnv
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.redact import REDACTION_MARKER
from candleviewer.audit.writer import AuditUnavailable, AuditWriter, AuditWriterStopped


def _writer(repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock, **kw: Any) -> AuditWriter:
    return AuditWriter(repo, str(tmp_path / "audit.wal"), clock=clock, sleep=repo.retry_sleep, **kw)


async def _drain(writer: AuditWriter) -> None:
    await writer.flush(5)


async def test_writer_genesis_and_chain_links_previous_entry(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    w = _writer(repo, tmp_path, clock)
    await w.start()
    for _ in range(3):
        await w.emit("auth.login", actor_label="alice")
    await _drain(w)
    await w.stop(1)
    assert repo.rows[0]["prev_hash"] == GENESIS
    for prev, cur in zip(repo.rows, repo.rows[1:], strict=False):
        assert cur["prev_hash"] == prev["entry_hash"]
    assert (await AuditQueryService(repo).verify()).verified


async def test_writer_secret_fields_absent_and_marker_present(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    w = _writer(repo, tmp_path, clock)
    await w.start()
    await w.emit(
        "auth.mfa_reset",
        actor_label="owner",
        before_state={"password_hash": "$argon2id$abc", "totp_seed": "JBSWY3DP", "role": "x"},
    )
    await _drain(w)
    await w.stop(1)
    stored = repo.rows[0]["before_state"]
    assert "argon2id" not in stored and "JBSWY3DP" not in stored
    assert json.loads(stored) == {
        "password_hash": REDACTION_MARKER,
        "totp_seed": REDACTION_MARKER,
        "role": "x",
    }
    wal_text = (tmp_path / "audit.wal").read_text(encoding="utf-8")
    assert "JBSWY3DP" not in wal_text


async def test_writer_postgres_outage_500_events_in_order_no_duplicates(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    w = _writer(repo, tmp_path, clock)
    await w.start()
    repo.down = True
    for i in range(500):
        await w.emit("orders.submit", actor_label="bot", object_id=str(i))
    for _ in range(20):
        await asyncio.sleep(0)
    assert repo.rows == [] and w.write_errors_total > 0
    repo.down = False
    await _drain(w)
    await w.stop(1)
    assert [r["object_id"] for r in repo.rows] == [str(i) for i in range(500)]
    assert (await AuditQueryService(repo).verify()).entries_checked == 500
    assert (await AuditQueryService(repo).verify()).verified


async def test_writer_crash_mid_buffer_replays_uncommitted_once(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    w1 = _writer(repo, tmp_path, clock)
    await w1.start()
    await w1.emit("auth.login", actor_label="a")
    await _drain(w1)
    repo.down = True
    await w1.emit("auth.logout", actor_label="a")
    for _ in range(10):
        await asyncio.sleep(0)
    await w1.stop(0.01)  # simulated kill: record is in the WAL, not in Postgres
    assert len(repo.rows) == 1
    repo.down = False
    w2 = _writer(repo, tmp_path, clock)
    await w2.start()
    await w2.emit("auth.login", actor_label="b")
    await _drain(w2)
    await w2.stop(1)
    assert [r["action"] for r in repo.rows] == ["auth.login", "auth.logout", "auth.login"]
    assert (await AuditQueryService(repo).verify()).verified


async def test_writer_unknown_action_rejected(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    w = _writer(repo, tmp_path, clock)
    await w.start()
    with pytest.raises(UnknownAuditAction):
        await w.emit("orders.yolo", actor_label="x")
    await w.stop(1)


async def test_writer_emit_when_stopped_raises(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    w = _writer(repo, tmp_path, clock)
    with pytest.raises(AuditWriterStopped):
        await w.emit("auth.login", actor_label="x")
    await w.stop(1)  # no task: no-op


async def test_writer_typed_ids_and_env_persisted(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    import uuid

    uid = uuid.uuid4()
    w = _writer(repo, tmp_path, clock)
    await w.start()
    await w.start()  # idempotent
    await w.emit(
        "orders.submit",
        actor_label="m",
        actor_user_id=str(uid),
        session_id=uid,
        request_id=None,
        env=ExchangeEnv.DEMO,
    )
    await _drain(w)
    await w.stop(1)
    assert repo.rows[0]["actor_user_id"] == str(uid) and repo.rows[0]["env"] == "demo"
    assert w.written_total == 1 and w.refused_total == 0 and w.buffer_depth == 0


async def test_writer_emit_is_durable_in_wal_before_returning(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    w = _writer(repo, tmp_path, clock)
    w._running = True  # no flusher task: only emit() itself runs
    await w.emit("auth.login", actor_label="durable")
    assert "durable" in (tmp_path / "audit.wal").read_text(encoding="utf-8")
    assert w.buffer_depth == 1 and repo.rows == []


async def test_writer_wal_write_failure_raises_and_alarms(
    repo: FakeAuditRepository,
    tmp_path: Path,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alarms: list[str] = []

    async def alarm(reason: str) -> None:
        alarms.append(reason)

    w = _writer(repo, tmp_path, clock, on_alarm=alarm)
    await w.start()

    def boom(_record: dict[str, Any]) -> int:
        raise OSError("disk gone")

    monkeypatch.setattr(w._wal, "append", boom)
    with pytest.raises(AuditUnavailable):
        await w.emit("auth.login", actor_label="x")
    assert w.refused_total == 1 and alarms and "OSError" in alarms[0]
    await w.stop(1)


async def test_writer_wal_full_with_postgres_down_refuses_never_drops(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    repo.down = True
    w = _writer(repo, tmp_path, clock, max_wal_bytes=1500)
    await w.start()
    accepted = 0
    with pytest.raises(AuditUnavailable):
        for i in range(100):
            await w.emit("auth.login", actor_label=str(i))
            accepted += 1
    assert 0 < accepted < 100
    repo.down = False
    await _drain(w)
    await w.stop(1)
    assert [r["actor_label"] for r in repo.rows] == [str(i) for i in range(accepted)]


async def test_writer_stop_without_flush_then_restart_delivers_exactly_once(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    repo.down = True
    w1 = _writer(repo, tmp_path, clock)
    await w1.start()
    for i in range(5):
        await w1.emit("orders.submit", actor_label="bot", object_id=str(i))
    await w1.stop(0.01)
    assert repo.rows == []
    repo.down = False
    w2 = _writer(repo, tmp_path, clock)
    await w2.start()
    await _drain(w2)
    await w2.stop(1)
    assert [r["object_id"] for r in repo.rows] == [str(i) for i in range(5)]


async def test_writer_replay_after_commit_before_cursor_is_idempotent(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    repo.down = True
    w1 = _writer(repo, tmp_path, clock)
    await w1.start()
    await w1.emit("auth.login", actor_label="a")
    await w1.stop(0.01)
    # Simulate a crash after the INSERT committed but before the cursor moved.
    (record,) = [json.loads(x) for x in (tmp_path / "audit.wal").read_text().splitlines()]
    repo.down = False
    await repo.insert(record)
    w2 = _writer(repo, tmp_path, clock)
    await w2.start()
    await _drain(w2)
    await w2.stop(1)
    assert len(repo.rows) == 1


async def test_writer_wal_full_compacts_committed_prefix(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    w = _writer(repo, tmp_path, clock, max_wal_bytes=1200)
    await w.start()
    for _ in range(10):
        await w.emit("auth.login", actor_label="alice")
        await _drain(w)
    await w.stop(1)
    assert len(repo.rows) == 10
    assert (tmp_path / "audit.wal").stat().st_size <= 1200
