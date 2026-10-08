"""Golden parity + replay-determinism harness for big trades (E22-T04, R2 exit #6/#7, 03 §4.2).

Fixture: `packages/fixtures/golden/bigtrade/` (recorded BTCUSDT window; README has provenance and
the regeneration procedure). `CV_REGEN_GOLDEN=1` rewrites the expected outputs and requires a
bumped `ALGO_VERSION`. No network, no wall clock, `tmp_path` only."""

from __future__ import annotations

import gzip
import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

import pytest

from candleviewer.orderflow.bigtrade import BigTradeEngine
from candleviewer.orderflow.bigtrade_models import (
    BigTradeAdvisoryEvent,
    BigTradeEvent,
    BigTradeThresholdEvent,
    TradeClusterEvent,
)
from tests.unit.orderflow import _bigtrade_golden_lib as G
from tests.unit.orderflow._bigtrade_recompute import Recompute

N250, PCT, CLUSTERED = (c.name for c in G.CASES)
_CFG = {c.name: c.cfg for c in G.CASES}


def _first_divergence(case: str, got: Sequence[str], want: Sequence[str]) -> str | None:
    """Name the first diverging event (its trade/cluster id) and field."""
    for i, (a, b) in enumerate(zip(got, want, strict=False)):
        if a != b:
            ja, jb = json.loads(a), json.loads(b)
            for field in sorted(set(ja) | set(jb)):
                if ja.get(field) != jb.get(field):
                    ident = ja.get("trade_id") or ja.get("cluster_id") or ja.get("kind")
                    return (
                        f"{case}: event #{i} ({ident}) field {field!r}: "
                        f"engine={ja.get(field)!r} golden={jb.get(field)!r}"
                    )
    if len(got) != len(want):
        return f"{case}: engine emitted {len(got)} events, golden has {len(want)}"
    return None


@pytest.fixture(scope="module")
def prints() -> list:  # type: ignore[type-arg]
    return G.fixture_events()


@pytest.fixture(scope="module")
def outputs(prints: list) -> dict[str, list]:  # type: ignore[type-arg]
    return {c.name: G.run(c.cfg, prints) for c in G.CASES}


@pytest.fixture(scope="module")
def sql() -> Recompute:
    tick = Decimal(json.loads(G.SUMMARY.read_text("utf-8"))["tick_size"])
    assert tick == G.TICK  # golden metadata and the engine tick must agree
    return Recompute(G.TRADES_GZ, tick)


def regen_guard(stored_version: str | None, current_version: str) -> None:
    """Refuse to regenerate the golden unless `ALGO_VERSION` was bumped (README procedure)."""
    if stored_version == current_version:
        raise RuntimeError("regenerating golden output requires bumping ALGO_VERSION")


def _stored_version() -> str | None:
    return json.loads(G.SUMMARY.read_text("utf-8"))["algo_version"] if G.SUMMARY.exists() else None


def test_regenerate_golden_only_with_algo_version_bump() -> None:
    if not G.REGEN:
        return
    regen_guard(_stored_version(), G.ALGO_VERSION)
    lines, summary = G.build_artifacts()
    G.write_expected(lines, summary)


def test_regen_guard_refuses_unchanged_algo_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(G, "REGEN", True)  # as if CV_REGEN_GOLDEN=1, version NOT bumped
    with pytest.raises(RuntimeError, match="bumping ALGO_VERSION"):
        regen_guard(_stored_version(), G.ALGO_VERSION)
    regen_guard(_stored_version(), G.ALGO_VERSION + "-next")  # a bump is allowed
    regen_guard(None, G.ALGO_VERSION)  # first generation is allowed


@pytest.mark.parametrize("case", [N250, PCT, CLUSTERED])
def test_engine_matches_golden_output(case: str, outputs: dict[str, list]) -> None:  # type: ignore[type-arg]
    summary = json.loads(G.SUMMARY.read_text("utf-8"))
    assert summary["algo_version"] == G.ALGO_VERSION, "algo_version drifted without regeneration"
    want = G.read_expected()[case]
    got = G.dump(outputs[case])
    msg = _first_divergence(case, got, want)
    assert msg is None, msg
    assert G.digest(got) == summary["cases"][case]["sha256"]


def test_notional_250000_flagged_set_equals_duckdb(
    outputs: dict[str, list],  # type: ignore[type-arg]
    sql: Recompute,
) -> None:
    flagged = [e for e in outputs[N250] if isinstance(e, BigTradeEvent)]
    want = sql.flagged_notional("250000")
    assert [e.trade_id for e in flagged] == [w["trade_id"] for w in want]
    for e, w in zip(flagged, want, strict=True):
        assert e.notional == Decimal(w["notional"]), e.trade_id
    assert sum(e.notional for e in flagged) == sum(Decimal(w["notional"]) for w in want)
    assert flagged == []  # the BTC tape peaks at ~31.6k USDT per print
    # The 250k cut is above the tape's max print: the empty set IS the expected parity result,
    # so also prove the harness is not vacuous at a cut that does flag prints.
    low = G.run(_CFG[N250].__class__(mode="notional", value=Decimal("30000")), G.fixture_events())
    got_low = [e.trade_id for e in low if isinstance(e, BigTradeEvent)]
    assert got_low == [w["trade_id"] for w in sql.flagged_notional("30000")]
    assert got_low


def test_percentile_flags_follow_emitted_threshold_schedule(
    outputs: dict[str, list],  # type: ignore[type-arg]
    sql: Recompute,
) -> None:
    out = outputs[PCT]
    flagged = [e for e in out if isinstance(e, BigTradeEvent)]
    sched = [
        (e.ts_event, e.effective_threshold_abs)
        for e in out
        if isinstance(e, BigTradeThresholdEvent) and e.effective_threshold_abs > 0
    ]
    sql.con.execute("CREATE OR REPLACE TABLE sched(ts BIGINT, thr DECIMAL(38,8))")
    sql.con.executemany("INSERT INTO sched VALUES (?, ?)", [(t, str(v)) for t, v in sched])
    rows = sql.con.execute(
        "SELECT p.trade_id FROM prints p ASOF JOIN sched s ON p.ts >= s.ts "
        "WHERE p.notional >= s.thr ORDER BY p.ts, p.trade_id"
    ).fetchall()
    assert [e.trade_id for e in flagged] == [r[0] for r in rows]
    # Two-sided rank check at many schedule points (window >= 40 prints). On this small recorded
    # window the trimmed P2 estimate of p99 measures rank 0.955..0.978 (see PR); an estimate that
    # is too low OR too high (e.g. base x1.5 -> rank ~1.0) must fail. 24 2.10's 1 % rank target is
    # for full windows and is owned by the quantile tests.
    checked = 0
    for ts, thr in sched[::20]:
        n, frac = sql.trailing_rank(ts, 3_600_000, str(thr))
        if n >= 40:
            checked += 1
            assert 0.90 <= frac <= 0.995, (ts, thr, n, frac)
    assert checked >= 10


def test_clusters_equal_duckdb_window_query(
    outputs: dict[str, list],  # type: ignore[type-arg]
    sql: Recompute,
) -> None:
    got = [e for e in outputs[CLUSTERED] if isinstance(e, TradeClusterEvent)]
    want = sql.clusters(1, 250)
    got.sort(key=lambda c: (c.first_ts_event, c.first_trade_id))
    assert len(got) == len(want), (len(got), len(want))
    for c, w in zip(got, want, strict=True):
        who = c.cluster_id
        assert list(c.trade_ids) == w["trade_ids"], who
        assert (c.side, c.price_bucket) == (w["side"], w["price_bucket"]), who
        assert (c.first_ts_event, c.last_ts_event) == (w["first_ts_event"], w["last_ts_event"]), who
        assert c.trade_id_count == w["trade_id_count"], who
        assert c.total_qty == Decimal(w["total_qty"]), who
        assert c.total_notional == Decimal(w["total_notional"]), who
        assert c.max_print_qty == Decimal(w["max_print_qty"]), who
    assert any(c.trade_id_count > 1 for c in got)  # merges exist on the recorded window
    assert sum(c.trade_id_count for c in got) == len(G.fixture_events())  # every print once


def _cluster_bytes(out: Sequence[object]) -> bytes:
    rows = [
        (c.cluster_id, c.trade_id_count, c.trade_ids, str(c.total_qty), c.bar_open_us(60_000_000))
        for c in out
        if isinstance(c, TradeClusterEvent)
    ]
    return json.dumps(rows, sort_keys=True).encode()


def test_randomised_batch_splits_are_byte_identical_on_recorded_window(
    prints: list,  # type: ignore[type-arg]
) -> None:
    cfg = _CFG[CLUSTERED]
    base = G.dump(G.run(cfg, prints))
    base_clusters = _cluster_bytes(G.run(cfg, prints))
    for seed in (101, 202, 303):
        out = G.run(cfg, prints, seed)
        assert _cluster_bytes(out) == base_clusters
        assert G.dump(out) == base  # full event stream (ids, ts, order) too


def test_double_run_determinism_on_dense_synthetic_stream() -> None:
    """Synthetic data is allowed HERE only (determinism, not golden): dense same-key bursts that
    straddle the deadline exercise every batch boundary position."""
    import random
    import uuid

    from candleviewer.domain.primitives import EventId
    from candleviewer.exchange.base.models import TradeEvent

    rng = random.Random(7)  # noqa: S311
    evs: list[TradeEvent] = []
    ts = 1_700_000_000_000_000
    for i in range(1500):
        ts += rng.choice((0, 0, 10_000, 120_000, 250_000, 250_001, 900_000))
        px = Decimal("63000.0") + Decimal(rng.randint(0, 5)) / 10
        q = Decimal(rng.randint(1, 40)) / 10
        evs.append(
            TradeEvent.model_validate(
                {
                    "event_id": EventId(uuid.UUID(int=i + 1)), "ts_event": ts, "ts_ingest": ts,
                    "source": "replay", "symbol": G.SYMBOL, "trade_id": f"s{i:06d}",
                    "price": px, "qty": q, "side": rng.choice(("buy", "sell")),
                    "is_block_trade": False, "price_ticks": int(px / G.TICK),
                    "notional": px * q, "seq": i + 1,
                }
            )
        )  # fmt: skip
    cfg = _CFG[CLUSTERED].__class__(
        mode="notional", value=Decimal("1000"), cluster_window_ms=250, cluster_tolerance_ticks=1
    )
    base = G.dump(G.run(cfg, evs))
    assert any(json.loads(x).get("trade_id_count", 0) > 3 for x in base)
    for seed in range(1, 6):
        assert G.dump(G.run(cfg, evs, seed)) == base


def test_live_and_replay_engine_state_equal(prints: list) -> None:  # type: ignore[type-arg]
    """R2 exit #1: the engine consuming the recorded stream ends in the state captured live
    (compared as a projection of engine state, see `engine_state`)."""
    for case in G.CASES:
        live = BigTradeEngine(G.SYMBOL, G.TICK, case.cfg, source="live")
        live_out = G.run(case.cfg, prints, 5, flush=False, engine=live)
        recorded = [
            e for e in live_out if isinstance(e, BigTradeThresholdEvent | BigTradeAdvisoryEvent)
        ]
        rep = BigTradeEngine(G.SYMBOL, G.TICK, case.cfg, source="replay", recorded=recorded)
        G.run(case.cfg, prints, 9, flush=False, engine=rep)  # different batch split
        assert rep.replay_mismatches == 0, case.name
        assert G.engine_state(rep) == G.engine_state(live), case.name


def test_flag_threshold_boundary_canonical_case_matches_duckdb(tmp_path: Path) -> None:
    """Prints exactly at, 0.0001 below and above the 30 000 / 250 000 notional cuts: pins the
    `measure >= threshold` comparison (the recorded tape never lands on a cut)."""
    rows = []
    for i, (px, q) in enumerate(
        [("62500.0", "0.48"), ("62500.0", "0.479999"), ("62500.0", "0.480001"),
         ("62500.0", "4"), ("62500.0", "3.999999"), ("62500.0", "4.000001")]
    ):  # fmt: skip
        rows.append(f"f{i:03d},{1_700_000_000_000_000 + i * 1000},buy,{px},{q},0")
    p = _write_csv(tmp_path / "flags.csv.gz", rows)
    evs = G.to_events(_rows(rows))
    sql = Recompute(p, G.TICK)
    for cut in ("30000", "250000"):
        cfg = _CFG[N250].__class__(mode="notional", value=Decimal(cut))
        got = [e.trade_id for e in G.run(cfg, evs) if isinstance(e, BigTradeEvent)]
        assert got == [w["trade_id"] for w in sql.flagged_notional(cut)], cut
        assert got  # the exact-at-threshold print IS flagged


NL = chr(10)
_COLS = ("trade_id", "ts_event_us", "side", "price", "qty", "is_block_trade")


def _rows(rows: list[str]) -> list[dict[str, str]]:
    return [dict(zip(_COLS, r.split(","), strict=True)) for r in rows]


def _write_csv(path: Path, rows: list[str]) -> Path:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        fh.write(",".join(_COLS) + NL + NL.join(rows) + NL)
    return path


def test_cluster_deadline_boundary_canonical_case_matches_duckdb(tmp_path: Path) -> None:
    """Hand-built canonical case (03 §4.2): prints exactly at, one us before and one us after the
    deadline (`first + 250 ms`). The recorded tape never lands on the boundary, so this is what
    pins the `<=` of the merge rule; DuckDB recomputes it independently."""
    base = 1_700_000_000_000_000
    gaps = [0, 250_000, 250_001, 0, 249_999, 250_000, 1]  # incl. exact, +1 and -1 around 250 ms
    ts, rows = base, []
    for i, g in enumerate(gaps):
        ts += g
        rows.append(f"b{i:03d},{ts},buy,63000.0,1.0,0")
    p = tmp_path / "boundary.csv.gz"
    with gzip.open(p, "wt", encoding="utf-8", newline="") as fh:
        fh.write("trade_id,ts_event_us,side,price,qty,is_block_trade\n" + "\n".join(rows) + "\n")
    evs = G.to_events(
        [
            dict(
                zip(
                    ("trade_id", "ts_event_us", "side", "price", "qty", "is_block_trade"),
                    r.split(","),
                    strict=True,
                )
            )
            for r in rows
        ]
    )
    cfg = _CFG[CLUSTERED].__class__(
        mode="notional", value=Decimal("1"), cluster_window_ms=250, cluster_tolerance_ticks=1
    )
    got = sorted(
        (c for c in G.run(cfg, evs) if isinstance(c, TradeClusterEvent)),
        key=lambda c: (c.first_ts_event, c.first_trade_id),
    )
    want = Recompute(p, G.TICK).clusters(1, 250)
    assert [list(c.trade_ids) for c in got] == [w["trade_ids"] for w in want]
    assert [len(c.trade_ids) for c in got] == [2, 3, 2]  # exact-deadline print merges, +1 us splits


def test_cluster_tolerance_two_ticks_matches_duckdb(tmp_path: Path) -> None:
    """Tolerance 2 (bucket width 0.2): 63000.0/.1 share a bucket (4 prints), .2/.3 the next (2)."""
    px = ["63000.0", "63000.1", "63000.2", "63000.3", "63000.1", "63000.0"]
    base = 1_700_000_000_000_000
    rows = [f"t{i:03d},{base + i * 10_000},sell,{p},1.0,0" for i, p in enumerate(px)]
    path = _write_csv(tmp_path / "tol2.csv.gz", rows)
    cfg = _CFG[CLUSTERED].__class__(
        mode="notional", value=Decimal("1"), cluster_window_ms=250, cluster_tolerance_ticks=2
    )
    got = sorted(
        (c for c in G.run(cfg, G.to_events(_rows(rows))) if isinstance(c, TradeClusterEvent)),
        key=lambda c: (c.first_ts_event, c.first_trade_id),
    )
    want = Recompute(path, G.TICK).clusters(2, 250)
    assert [list(c.trade_ids) for c in got] == [w["trade_ids"] for w in want]
    assert [len(c.trade_ids) for c in got] == [4, 2]


def test_second_symbol_synthetic_tick_001_smoke_engine_equals_oracle(tmp_path: Path) -> None:
    """SYNTHETIC prints (ETHUSDT-shaped, tick 0.01): oracle-shape/determinism smoke ONLY, not a
    golden (C-13.5). Proves the oracle's tick is a parameter: with tick 0.01 the prices 2000.00 /
    2000.01 share a 2-tick bucket, 2000.02 / 2000.03 the next (a fixed 0.1 tick would differ)."""
    tick = Decimal("0.01")
    px = ["2000.00", "2000.01", "2000.02", "2000.03", "2000.01", "2000.00", "2000.50"]
    base = 1_700_000_000_000_000
    rows = [f"s{i:03d},{base + i * 10_000},buy,{p},1.0,0" for i, p in enumerate(px)]
    path = _write_csv(tmp_path / "eth_synth.csv.gz", rows)
    cfg = _CFG[CLUSTERED].__class__(
        mode="notional", value=Decimal("1"), cluster_window_ms=250, cluster_tolerance_ticks=2
    )
    evs = G.to_events(_rows(rows), "ETHUSDT", tick)
    eng = BigTradeEngine("ETHUSDT", tick, cfg)
    got = sorted(
        (c for c in G.run(cfg, evs, engine=eng) if isinstance(c, TradeClusterEvent)),
        key=lambda c: (c.first_ts_event, c.first_trade_id),
    )
    want = Recompute(path, tick).clusters(2, 250)
    assert [list(c.trade_ids) for c in got] == [w["trade_ids"] for w in want]
    assert [(c.side, c.price_bucket) for c in got] == [(w["side"], w["price_bucket"]) for w in want]
    assert [len(c.trade_ids) for c in got] == [4, 2, 1]
    with pytest.raises(ValueError, match="tick_size"):
        Recompute(path, Decimal("0.000000001"))


def test_sub_cent_synthetic_tick_0001_smoke_engine_equals_oracle(tmp_path: Path) -> None:
    """SYNTHETIC prints, tick 0.0001, tolerance 2 (bucket width 0.0002): smoke only (C-13.5).
    Prices sit on both sides of bucket edges (0.5000/0.5001 | 0.5002/0.5003 | 0.5004)."""
    tick = Decimal("0.0001")
    px = ["0.5000", "0.5001", "0.5002", "0.5003", "0.5001", "0.5004", "0.4999", "0.5000"]
    base = 1_700_000_000_000_000
    rows = [f"u{i:03d},{base + i * 10_000},sell,{p},10.0,0" for i, p in enumerate(px)]
    path = _write_csv(tmp_path / "subcent.csv.gz", rows)
    cfg = _CFG[CLUSTERED].__class__(
        mode="notional", value=Decimal("1"), cluster_window_ms=250, cluster_tolerance_ticks=2
    )
    evs = G.to_events(_rows(rows), "XRPUSDT", tick)
    eng = BigTradeEngine("XRPUSDT", tick, cfg)
    got = sorted(
        (c for c in G.run(cfg, evs, engine=eng) if isinstance(c, TradeClusterEvent)),
        key=lambda c: (c.first_ts_event, c.first_trade_id),
    )
    want = Recompute(path, tick).clusters(2, 250)
    assert [list(c.trade_ids) for c in got] == [w["trade_ids"] for w in want]
    assert [(c.side, c.price_bucket) for c in got] == [(w["side"], w["price_bucket"]) for w in want]
    assert [len(c.trade_ids) for c in got] == [
        4,
        2,
        1,
        1,
    ]  # buckets 2500 (x4), 2501 (x2), 2502, 2499
