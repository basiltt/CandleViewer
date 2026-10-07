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
    return Recompute(G.TRADES_GZ)


def test_regenerate_golden_only_with_algo_version_bump(
    prints: list,  # type: ignore[type-arg]
) -> None:
    if not G.REGEN:
        return
    old = json.loads(G.SUMMARY.read_text("utf-8"))["algo_version"] if G.SUMMARY.exists() else None
    assert old != G.ALGO_VERSION, "regenerating golden output requires bumping ALGO_VERSION"
    lines, summary = G.build_artifacts()
    G.write_expected(lines, summary)


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
    assert len(flagged) == 0 or flagged  # the BTC tape peaks at ~31.6k USDT per print
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
    # Sanity bound only: on this small (~180-sample) window the trimmed P2 estimate lands at
    # ~rank 0.95 (24 2.10's 1 % rank target is for full windows, owned by the quantile tests).
    n, frac = sql.trailing_rank(out[-1].ts_event, 3_600_000, str(sched[-1][1]))
    assert n > 100 and frac >= 0.90


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
    """R2 exit #1: the engine consuming the recorded stream ends in the state captured live."""
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
    want = Recompute(p).clusters(1, 250)
    assert [list(c.trade_ids) for c in got] == [w["trade_ids"] for w in want]
    assert [len(c.trade_ids) for c in got] == [2, 3, 2]  # exact-deadline print merges, +1 us splits
