"""Deterministic clustering (US-BIG-004 sc.1-3, 24-internal-schemas §2.10 "Cluster key")."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.exchange.base.models import TradeEvent
from candleviewer.orderflow import limits as L
from candleviewer.orderflow.bigtrade import BigTradeEngine
from candleviewer.orderflow.bigtrade_cluster import Clusterer, cluster_prints
from candleviewer.orderflow.bigtrade_models import BigTradeConfig, BigTradeOutput, TradeClusterEvent
from tests.unit.orderflow._bigtrade_helpers import TICK, trade

MS = 1000


def _cfg(window: int = 250, tol: int = 1) -> BigTradeConfig:
    return BigTradeConfig(value=Decimal("0"), cluster_window_ms=window, cluster_tolerance_ticks=tol)


def _clusters(out: Sequence[object]) -> list[TradeClusterEvent]:
    return [e for e in out if isinstance(e, TradeClusterEvent)]


def test_merge_exactly_at_deadline_and_split_one_us_after() -> None:
    eng = BigTradeEngine("BTCUSDT", TICK, _cfg())
    a, b, c = (
        trade(0, "100.0", "1"),
        trade(250 * MS, "100.0", "2"),
        trade(250 * MS + 1, "100.0", "4"),
    )
    first = _clusters(eng.process([a, b]) + eng.process([c]))
    assert len(first) == 1 and first[0].cluster_size == 1 + 1  # a+b merged; c split
    assert first[0].close_reason == "deadline" and first[0].total_qty == Decimal("3")
    rest = eng.flush()
    assert rest[0].trade_ids == (c.trade_id,)


def test_one_bucket_outside_tolerance_and_opposite_side_open_new_clusters() -> None:
    eng = BigTradeEngine("BTCUSDT", TICK, _cfg(tol=1))
    out = eng.process(
        [trade(0, "100.0", "1"), trade(1, "100.1", "1"), trade(2, "100.0", "1", "sell")]
    )
    out += eng.flush()
    keys = sorted((c.side, c.price_bucket) for c in _clusters(out))
    assert keys == [("buy", 1000), ("buy", 1001), ("sell", 1000)]


def test_tolerance_ticks_widen_bucket_from_tick_size() -> None:
    c = Clusterer(Decimal("0.5"), 250, 4)
    assert c.bucket(Decimal("100.0")) == c.bucket(Decimal("101.5")) == 50
    assert c.bucket(Decimal("102.0")) == 51
    assert Clusterer(Decimal("0.5"), 250, 0).bucket(Decimal("100.5")) == 201


def test_cluster_spanning_bar_boundary_attributed_to_first_print_bar() -> None:
    bar = 60_000 * MS
    eng = BigTradeEngine("BTCUSDT", TICK, _cfg(window=250))
    out = eng.process([trade(bar - 100 * MS, "100.0", "1"), trade(bar + 100 * MS, "100.0", "1")])
    (cl,) = _clusters([*out, *eng.flush()])
    assert cl.cluster_size == 2 and cl.bar_open_us(bar) == 0  # bar N, not N+1
    assert cl.vwap == Decimal("100.0") and cl.estimated is True


def test_cluster_window_zero_short_circuits() -> None:
    eng = BigTradeEngine("BTCUSDT", TICK, _cfg(window=0))
    assert _clusters([*eng.process([trade(0, "100.0", "1")]), *eng.flush()]) == []


def test_trade_ids_bounded_with_truncated_flag() -> None:
    eng = BigTradeEngine("BTCUSDT", TICK, _cfg(window=2000))
    prints = [trade(i, "100.0", "1", trade_id=f"id{i:04d}") for i in range(100)]
    (cl,) = _clusters([*eng.process(prints), *eng.flush()])
    assert cl.trade_id_count == 100 and len(cl.trade_ids) == L.CLUSTER_IDS_MAX
    assert cl.trade_ids_truncated and cl.last_trade_id == "id0099"


def test_open_key_cap_evicts_oldest_and_counts_truncation() -> None:
    hits: list[int] = []
    c = Clusterer(TICK, 5000, 0, on_truncate=lambda: hits.append(1))
    closed = []
    for i in range(L.CLUSTER_KEYS_MAX + 1):
        closed += c.add(trade(i, f"{100 + i * 0.1:.1f}", "1"))
    assert [r for _, r in closed] == ["evicted"] and hits == [1]


def test_prints_buffer_effective_cap_evicts() -> None:
    c = Clusterer(TICK, 1, 0)
    closed = []
    for i in range(L.PRINTS_BUFFER_MAX + 1):
        closed += c.add(trade(0, "100.0", "1", trade_id=f"b{i}"))
    assert closed and closed[0][1] == "evicted"


def test_recompute_from_stored_prints_matches_live_path() -> None:
    prints = [trade(i * 100 * MS, "100.0", "1") for i in range(20)]
    eng = BigTradeEngine("BTCUSDT", TICK, _cfg(window=1000))
    live = _clusters([*eng.process(prints), *eng.flush()])
    stored = cluster_prints(list(reversed(prints)), TICK, 1000, 1)
    assert [c.trade_id_count for c in live] == [c.count for c, _ in stored]


_prints = st.lists(
    st.tuples(
        st.integers(0, 3000), st.integers(0, 6), st.sampled_from(["buy", "sell"]), st.integers(1, 9)
    ),
    min_size=1,
    max_size=60,
)


def _run(evs: list[TradeEvent], splits: list[int]) -> list[tuple[object, ...]]:
    eng = BigTradeEngine("BTCUSDT", TICK, _cfg(window=250, tol=1))
    out: list[BigTradeOutput] = []
    i = 0
    for n in [*splits, len(evs)]:
        out += eng.process(evs[i : i + n])
        i += n
    out += eng.flush()
    return [
        (c.cluster_id, c.trade_ids, c.total_qty, c.first_ts_event, c.close_reason)
        for c in _clusters(out)
    ]


@settings(max_examples=150, deadline=None)
@given(raw=_prints, splits=st.lists(st.integers(1, 10), max_size=8), data=st.data())
def test_property_batching_and_in_batch_order_invariance(
    raw: list[tuple[int, int, str, int]], splits: list[int], data: st.DataObject
) -> None:
    """Same prints, different batch splits + any order WITHIN a batch -> identical clusters.
    (The bus guarantees batch order per symbol; within a batch the engine sorts.)"""
    evs = sorted(
        (
            trade(ts * MS, f"{100 + p * 0.1:.1f}", str(q), s, trade_id=f"k{n:03d}")
            for n, (ts, p, s, q) in enumerate(raw)
        ),
        key=lambda e: (e.ts_event, e.trade_id),
    )
    baseline = _run(evs, [])
    shuffled = data.draw(st.permutations(evs[: splits[0]] if splits else evs))
    head = len(shuffled)
    assert _run([*shuffled, *evs[head:]], splits) == baseline
