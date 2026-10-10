"""E16-T03 backpressure ladder: queue -> WAL spill -> explicit drop gap; WAL replay."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.recorder.wal import (
    CORRUPT_DIR,
    SpillWal,
    WalBudget,
    WalRecord,
    encode_frame,
)
from candleviewer.recorder.writer import STREAMS, dedup_sorted
from tests.unit.recorder._writer_helpers import T0, make_writer, trade


def _rec(i: int, ts: int | None = None) -> WalRecord:
    return WalRecord("trades", "BTCUSDT", T0 + i if ts is None else ts, i, 0, {"trade_id": f"t{i}"})


# --- WAL file format ---------------------------------------------------------------------------


def test_wal_frame_round_trip(tmp_path: Path) -> None:
    wal = SpillWal(tmp_path, WalBudget(1 << 20))
    recs = [_rec(i) for i in range(3)]
    assert wal.append(recs) == 3
    assert wal.begin_replay()
    assert wal.read_replay().records == recs
    wal.finish_replay()
    assert not wal.has_data() and not wal.begin_replay()


def test_wal_crc_failure_ends_replay_and_quarantines_tail(tmp_path: Path) -> None:
    budget = WalBudget(1 << 20)
    wal = SpillWal(tmp_path, budget)
    wal.append([_rec(0), _rec(1), _rec(2)])
    data = bytearray(wal.spill_path.read_bytes())
    second = len(encode_frame(_rec(0)))
    data[second + 10] ^= 0xFF  # flip a payload byte of frame 2
    wal.spill_path.write_bytes(bytes(data))
    wal.begin_replay()
    result = wal.read_replay()
    assert [r.seq for r in result.records] == [0]
    assert result.corrupt_bytes == len(data) - second
    (quarantined,) = (tmp_path / CORRUPT_DIR).iterdir()
    assert quarantined.read_bytes() == bytes(data[second:])


def test_wal_torn_tail_is_quarantined(tmp_path: Path) -> None:
    wal = SpillWal(tmp_path, WalBudget(1 << 20))
    wal.append([_rec(0)])
    with wal.spill_path.open("ab") as fh:
        fh.write(b"\x00\x00\x01")
    wal.begin_replay()
    assert wal.read_replay().corrupt_bytes == 3


def test_wal_budget_refuses_and_is_recovered_on_restart(tmp_path: Path) -> None:
    frame = len(encode_frame(_rec(0)))
    budget = WalBudget(frame * 2)
    wal = SpillWal(tmp_path, budget)
    assert wal.append([_rec(0), _rec(1), _rec(2)]) == 2
    assert budget.used == frame * 2
    budget2 = WalBudget(frame * 2)
    SpillWal(tmp_path, budget2)
    assert budget2.used == frame * 2


def test_wal_budget_rejects_zero() -> None:
    with pytest.raises(ValueError):
        WalBudget(0)


def test_dedup_sorted_orders_by_exch_ts_and_drops_duplicates() -> None:
    a, b, c = _rec(1, ts=T0 + 30), _rec(2, ts=T0 + 10), _rec(3, ts=T0 + 20)
    assert dedup_sorted([a, b, c, b, a]) == [b, c, a]


# --- ladder through the writer ----------------------------------------------------------------


async def test_queue_bound_spills_to_wal(tmp_path: Path) -> None:
    w, sink, *_ = make_writer(tmp_path, max_queue_rows=3)
    for i in range(3):
        await w.on_trade(trade(i))
    assert w.backlog_rows == 3 and w.spill_bytes == 0
    await w.on_trade(trade(3))
    # Queue + overflow go to the WAL together, oldest first; nothing dropped.
    assert w.backlog_rows == 0 and w.spill_bytes > 0 and w.is_spilling("trades")
    await w.recover()
    assert [r["trade_id"] for r in sink.rows("trades")] == ["t0", "t1", "t2", "t3"]
    assert w.spill_bytes == 0 and not w.is_spilling("trades")


async def test_questdb_down_spills_then_replays_in_exch_ts_order(tmp_path: Path) -> None:
    """Scenario: QuestDB stopped -> WAL, no drops; on return replay in exch_ts order, truncate."""
    w, sink, store, events, clock = make_writer(tmp_path)
    sink.down.add("*")
    for i in (5, 1, 3):
        await w.on_trade(trade(i))
    clock.advance(0.2)
    await w.pump("trades")  # write fails -> spill mode
    for i in (4, 2):
        await w.on_trade(trade(i))  # arrive while spilling -> WAL directly
    assert w.spill_bytes > 0 and sink.rows("trades") == []
    clock.advance(1.0)
    await w.pump("trades")  # retry while still down: stays spilled
    assert w.is_spilling("trades")
    sink.down.clear()
    await w.recover()
    assert [r["trade_id"] for r in sink.rows("trades")] == ["t1", "t2", "t3", "t4", "t5"]
    assert w.spill_bytes == 0 and not any((tmp_path / "wal" / "trades").glob("*.wal"))
    assert store.gaps == [] and events.events == []


async def test_spill_replay_retried_on_cadence(tmp_path: Path) -> None:
    w, sink, _, _, clock = make_writer(tmp_path)
    sink.down.add("*")
    await w.on_trade(trade(1))
    clock.advance(0.2)
    await w.pump("trades")
    sink.down.clear()
    clock.advance(0.5)
    await w.pump("trades")
    assert sink.rows("trades") == []  # before replay_retry_s
    clock.advance(0.5)
    await w.pump("trades")
    assert len(sink.rows("trades")) == 1


async def test_wal_full_drops_with_gap_row_and_critical_event(tmp_path: Path) -> None:
    """Scenario: WAL at cap + QuestDB down -> drop, recording_gaps row, critical event."""
    frame = len(encode_frame(_rec(0))) + 120  # a real trade frame is a bit larger
    w, sink, store, events, clock = make_writer(tmp_path, wal_max_bytes=frame * 2)
    sink.down.add("*")
    for i in range(1, 7):
        await w.on_trade(trade(i))
    clock.advance(0.2)
    await w.pump("trades")
    gaps = w.pending_gaps()
    ((key, (first, last)),) = gaps.items()
    assert key == ("BTCUSDT", "trades") and first > T0 and last == T0 + 6
    (event,) = events.events
    assert event.severity == "critical" and event.details["symbol"] == "BTCUSDT"
    await w.on_trade(trade(7))
    assert len(events.events) == 1  # one critical event per episode, window coalesced
    await w.flush_gaps()
    (gap,) = store.gaps
    assert gap["cause"] == "backpressure_drop" and gap["stream"] == "trades"
    assert gap["end"] > gap["start"]
    await w.flush_counters()
    kw = store.counters[0][1]
    assert kw["messages_received"] == 7
    assert kw["messages_dropped"] == 7 - len(sink.rows("trades")) - _wal_rows(w, tmp_path)


def _wal_rows(w: object, tmp_path: Path) -> int:
    wal = SpillWal(tmp_path / "wal" / "trades", WalBudget(1 << 30))
    wal.begin_replay()
    return len(wal.read_replay().records)


async def test_disk_error_on_spill_is_a_recorded_drop(tmp_path: Path) -> None:
    """Chaos 13 (disk full): OSError on append -> drop + gap, never silent."""
    w, sink, _, events, clock = make_writer(tmp_path)
    lane_wal = w._lanes["trades"].wal

    def boom(_: list[WalRecord]) -> int:
        raise OSError(28, "No space left on device")

    lane_wal.append = boom  # type: ignore[method-assign]
    sink.down.add("*")
    await w.on_trade(trade(1))
    clock.advance(0.2)
    await w.pump("trades")
    assert ("BTCUSDT", "trades") in w.pending_gaps() and events.events


async def test_gap_retained_when_store_fails(tmp_path: Path) -> None:
    w, sink, store, _, clock = make_writer(tmp_path, wal_max_bytes=1)
    sink.down.add("*")
    await w.on_trade(trade(1))
    clock.advance(0.2)
    await w.pump("trades")
    store.fail = True
    await w.flush_gaps()
    assert w.pending_gaps()
    store.fail = False
    await w.flush_gaps()
    assert not w.pending_gaps() and len(store.gaps) == 1


async def test_interrupted_replay_restarts_without_duplicates(tmp_path: Path) -> None:
    """Scenario: replay interrupted halfway and restarted -> no duplicate keys (sink dedups
    like QuestDB DEDUP UPSERT KEYS; the in-process dedup covers WAL-internal duplicates)."""
    w, sink, _, _, clock = make_writer(tmp_path, flush_rows=2)
    sink.down.add("*")
    for i in range(6):
        await w.on_trade(trade(i))
    await w.on_trade(trade(3))  # an upstream duplicate inside the WAL
    clock.advance(0.2)
    await w.pump("trades")
    sink.down.clear()
    sink.fail_after = 1  # first batch lands, second dies
    await w.recover()
    assert w.is_spilling("trades")
    sink.fail_after = None
    # A fresh process restarts from replay.wal (startup recovery).
    w2, sink2, *_ = make_writer(tmp_path, flush_rows=2)
    sink2.flushed = sink.flushed
    await w2.start()
    await w2.stop()
    keys = [(r["symbol"], r["ts"], r["seq"]) for r in sink.rows("trades")]
    assert sorted(set(keys)) == sorted({("BTCUSDT", T0 + i, i) for i in range(6)})
    assert len(keys) - len(set(keys)) <= 2  # only the re-sent first batch (deduped by QuestDB)
    assert not w2.is_spilling("trades") and w2.spill_bytes == 0


# --- property: no row lost or duplicated across spill/replay/flush interleavings ---------------

_OPS = st.lists(
    st.sampled_from(["event", "event", "event", "down", "up", "tick", "recover"]),
    min_size=1,
    max_size=60,
)


@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(ops=_OPS)
async def test_property_no_row_lost_or_duplicated(
    tmp_path_factory: pytest.TempPathFactory, ops: list[str]
) -> None:
    tmp = tmp_path_factory.mktemp("prop")
    w, sink, _, _, clock = make_writer(tmp, max_queue_rows=4, flush_rows=3)
    n = 0
    for op in ops:
        if op == "event":
            await w.on_trade(trade(n))
            n += 1
        elif op == "down":
            sink.down.add("*")
        elif op == "up":
            sink.down.clear()
        elif op == "tick":
            clock.advance(0.25)
            for s in STREAMS:
                await w.pump(s)
        else:
            await w.recover()
    sink.down.clear()
    await w.recover()
    await w.stop()
    got = [r["trade_id"] for r in sink.rows("trades")]
    assert sorted(set(got)) == sorted({f"t{i}" for i in range(n)})
    assert len(got) == len(set(got))  # the fake sink never fails mid-batch here
    assert w.pending_gaps() == {}
