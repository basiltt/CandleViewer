"""E16-T03 WAL file: batched append, streaming external-sort replay, checkpoint, quarantine."""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.recorder.wal import (
    CORRUPT_DIR,
    RUNS_DIR,
    SpillWal,
    WalBudget,
    WalRecord,
    encode_frame,
)
from candleviewer.recorder.writer import dedup_sorted
from tests.unit.recorder._writer_helpers import T0, FsyncCounter


def _rec(i: int, ts: int | None = None, symbol: str = "BTCUSDT") -> WalRecord:
    return WalRecord("trades", symbol, T0 + i if ts is None else ts, i, 0, {"trade_id": f"t{i}"})


def _wal(
    tmp_path: Path, budget: int = 1 << 20, chunk: int = 50_000
) -> tuple[SpillWal, WalBudget, FsyncCounter]:
    b, f = WalBudget(budget), FsyncCounter()
    wal = SpillWal(tmp_path, b, chunk_rows=chunk, fsync=f)
    wal.open()
    return wal, b, f


def _replay_all(wal: SpillWal) -> list[WalRecord]:
    assert wal.begin_replay().pending
    out = [rec for _, rec in wal.iter_replay()]
    wal.finish_replay()
    return out


def test_wal_frame_round_trip(tmp_path: Path) -> None:
    wal, budget, _ = _wal(tmp_path)
    recs = [_rec(i) for i in range(3)]
    assert wal.append(recs) == 3
    assert _replay_all(wal) == recs
    assert not wal.has_data() and budget.used == 0


def test_append_is_one_write_and_one_fsync_per_batch(tmp_path: Path) -> None:
    wal, _, fsync = _wal(tmp_path)
    assert wal.append([_rec(i) for i in range(500)]) == 500
    assert fsync.calls == 1


def test_constructor_does_no_io(tmp_path: Path) -> None:
    SpillWal(tmp_path / "x", WalBudget(10))
    assert not (tmp_path / "x").exists()


def test_replay_streams_a_wal_larger_than_the_chunk_bound(tmp_path: Path) -> None:
    """External sort: 5 runs of <=4 rows each, merged in exch_ts order across runs."""
    wal, _, _ = _wal(tmp_path, chunk=4)
    ts = [17, 3, 11, 19, 2, 7, 13, 5, 1, 23, 29, 31, 37, 0, 41, 43, 47, 53, 59, 61]
    for i, t in enumerate(ts):
        wal.append([_rec(i, ts=T0 + t)])
    assert wal.begin_replay().pending
    assert len(list((tmp_path / RUNS_DIR).glob("*.run"))) == 5
    out = [rec.exch_ts - T0 for _, rec in wal.iter_replay()]
    assert out == sorted(ts)


def test_replay_resumes_from_the_checkpoint(tmp_path: Path) -> None:
    wal, _, _ = _wal(tmp_path, chunk=3)
    wal.append([_rec(i) for i in range(10)])
    wal.begin_replay()
    it = wal.iter_replay()
    first = [next(it) for _ in range(4)]
    it.close()
    wal.commit(first[-1][0] + 1)
    # A fresh process (new SpillWal) resumes after the 4 committed records.
    wal2, _, _ = _wal(tmp_path, chunk=3)
    assert wal2.begin_replay().pending
    assert [r.seq for _, r in wal2.iter_replay()] == list(range(4, 10))


def test_merge_suppresses_duplicate_keys(tmp_path: Path) -> None:
    wal, _, _ = _wal(tmp_path, chunk=2)
    wal.append([_rec(1), _rec(2), _rec(1), _rec(3), _rec(2)])
    assert [r.seq for r in _replay_all(wal)] == [1, 2, 3]


def test_crc_failure_quarantines_tail_counted_in_budget(tmp_path: Path) -> None:
    wal, budget, _ = _wal(tmp_path)
    wal.append([_rec(0)])
    wal.append([_rec(1, symbol="ETHUSDT"), _rec(2, symbol="ETHUSDT")])
    data = bytearray(wal.spill_path.read_bytes())
    second = len(encode_frame(_rec(0)))
    data[second + 10] ^= 0xFF
    wal.spill_path.write_bytes(bytes(data))
    prep = wal.begin_replay()
    assert prep.corrupt_bytes == len(data) - second
    # ETHUSDT lived only in the corrupt tail: it still gets a window (from the meta).
    assert prep.corrupt_windows["ETHUSDT"] == (T0 + 1, T0 + 2)
    assert [r.seq for _, r in wal.iter_replay()] == [0]
    (quarantined,) = (tmp_path / CORRUPT_DIR).iterdir()
    assert quarantined.read_bytes() == bytes(data[second:])
    wal.finish_replay()
    assert budget.used == prep.corrupt_bytes  # quarantine still counts against the cap
    b2 = WalBudget(1 << 20)
    SpillWal(tmp_path, b2).open()
    assert b2.used == prep.corrupt_bytes


def test_torn_tail_is_quarantined(tmp_path: Path) -> None:
    wal, _, _ = _wal(tmp_path)
    wal.append([_rec(0)])
    with wal.spill_path.open("ab") as fh:
        fh.write(b"\x00\x00\x01")
    assert wal.begin_replay().corrupt_bytes == 3


def test_oserror_while_building_runs_keeps_replay_file(tmp_path: Path) -> None:
    wal, budget, _ = _wal(tmp_path)
    wal.append([_rec(0), _rec(1)])
    used = budget.used

    def boom(_fd: int) -> None:
        raise OSError(28, "No space left on device")

    wal._fsync = boom
    with pytest.raises(OSError):
        wal.begin_replay()
    assert wal.replay_path.exists() and not (tmp_path / RUNS_DIR).exists()
    assert budget.used == used
    wal._fsync = FsyncCounter()
    assert [r.seq for r in _replay_all(wal)] == [0, 1]


def test_budget_refuses_and_is_recovered_on_restart(tmp_path: Path) -> None:
    frame = len(encode_frame(_rec(0)))
    wal, _, _ = _wal(tmp_path, budget=frame * 2)
    assert wal.append([_rec(0), _rec(1), _rec(2)]) == 2
    b2 = WalBudget(frame * 2)
    SpillWal(tmp_path, b2).open()
    assert b2.used == frame * 2


def test_budget_and_chunk_reject_zero(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        WalBudget(0)
    with pytest.raises(ValueError):
        SpillWal(tmp_path, WalBudget(1), chunk_rows=0)


def test_dedup_sorted_orders_by_exch_ts_and_drops_duplicates() -> None:
    a, b, c = _rec(1, ts=T0 + 30), _rec(2, ts=T0 + 10), _rec(3, ts=T0 + 20)
    assert dedup_sorted([a, b, c, b, a]) == [b, c, a]


# --- review round 2: checkpoint binding and run verification ---------------------------------


def _write_checkpoint(tmp_path: Path, body: bytes) -> None:
    (tmp_path / RUNS_DIR / "CHECKPOINT").write_bytes(body)


@pytest.mark.parametrize(
    "body",
    [
        b'{"ck": 3, "total": 999}',  # bound to another run set (stale)
        b'{"ck": 999999999, "total": 10}',  # past EOF
        b'{"ck": -1, "total": 10}',
        b"999999999",  # legacy/garbage
    ],
)
def test_invalid_checkpoint_restarts_full_replay(tmp_path: Path, body: bytes) -> None:
    wal, _, _ = _wal(tmp_path, chunk=3)
    wal.append([_rec(i) for i in range(10)])
    wal.begin_replay()
    _write_checkpoint(tmp_path, body)
    got = [r.seq for _, r in wal.iter_replay()]
    assert got == list(range(10))
    assert wal.replay_complete() and wal.warnings


def test_valid_checkpoint_is_honoured_without_warning(tmp_path: Path) -> None:
    wal, _, _ = _wal(tmp_path, chunk=3)
    wal.append([_rec(i) for i in range(10)])
    wal.begin_replay()
    wal.commit(7)
    assert [r.seq for _, r in wal.iter_replay()] == [7, 8, 9]
    assert wal.replay_complete() and not wal.warnings


def test_empty_run_set_with_checkpoint_finishes_cleanly(tmp_path: Path) -> None:
    wal, budget, _ = _wal(tmp_path)
    wal.append([_rec(0)])
    wal.begin_replay()
    for run in (tmp_path / RUNS_DIR).glob("*.run"):
        run.unlink()
    budget.used = 0
    (tmp_path / RUNS_DIR / "MANIFEST").write_bytes(b"{}")
    wal.commit(0)
    assert wal.verify_runs().corrupt_bytes == 0
    assert list(wal.iter_replay()) == [] and wal.replay_complete()
    wal.finish_replay()
    assert not (tmp_path / RUNS_DIR).exists()


def test_truncated_run_is_quarantined_with_its_windows(tmp_path: Path) -> None:
    wal, budget, _ = _wal(tmp_path, chunk=2)
    wal.append([_rec(0), _rec(1), _rec(2, symbol="ETHUSDT"), _rec(3, symbol="ETHUSDT")])
    wal.begin_replay()
    run = tmp_path / RUNS_DIR / "000001.run"
    data = run.read_bytes()
    run.write_bytes(data[: len(data) // 2])
    used = budget.used
    prep = wal.verify_runs()
    assert prep.corrupt_bytes == len(data) // 2
    assert prep.corrupt_windows == {"ETHUSDT": (T0 + 2, T0 + 3)}
    assert any(p.name.endswith(".run.wal") for p in (tmp_path / CORRUPT_DIR).iterdir())
    assert budget.used == used  # quarantined bytes stay counted
    assert [r.seq for _, r in wal.iter_replay()] == [0, 1] and wal.replay_complete()


def test_run_damaged_after_verification_is_not_reported_complete(tmp_path: Path) -> None:
    wal, _, _ = _wal(tmp_path, chunk=5)
    wal.append([_rec(i) for i in range(5)])
    wal.begin_replay()
    wal.verify_runs()
    run = next((tmp_path / RUNS_DIR).glob("*.run"))
    data = run.read_bytes()
    run.write_bytes(data[: len(data) - 3])
    list(wal.iter_replay())
    assert not wal.replay_complete()
