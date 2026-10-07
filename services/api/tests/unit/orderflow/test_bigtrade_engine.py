"""BigTradeEngine thresholds, over-flag cap, dedupe, replay (E22-T01 Gherkin)."""

from __future__ import annotations

import random
from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise

import pytest

from candleviewer.orderflow.bigtrade import BigTradeEngine
from candleviewer.orderflow.bigtrade_models import (
    BigTradeAdvisoryEvent,
    BigTradeConfig,
    BigTradeConfigInvalid,
    BigTradeEvent,
    BigTradeThresholdEvent,
)
from tests.unit.orderflow._bigtrade_helpers import TICK, trade

S = 1_000_000  # µs per second


def _flagged(out: Sequence[object]) -> set[str]:
    return {e.trade_id for e in out if isinstance(e, BigTradeEvent)}


def test_notional_mode_flags_exactly_prints_at_or_above_threshold() -> None:
    eng = BigTradeEngine("BTCUSDT", TICK, BigTradeConfig(mode="notional", value=Decimal("1000")))
    prints = [
        trade(1 * S, "100.0", "10"),
        trade(2 * S, "100.0", "9.99"),
        trade(3 * S, "200.0", "6"),
    ]
    out = eng.process(prints)
    assert _flagged(out) == {prints[0].trade_id, prints[2].trade_id}
    ev = next(e for e in out if isinstance(e, BigTradeEvent))
    assert ev.threshold_abs == Decimal("1000") and not ev.estimated and not ev.capped


def test_absolute_size_mode_compares_qty_not_notional() -> None:
    eng = BigTradeEngine("BTCUSDT", TICK, BigTradeConfig(mode="absolute_size", value=Decimal("5")))
    prints = [trade(S, "60000.0", "4.9"), trade(2 * S, "1.0", "5")]
    assert _flagged(eng.process(prints)) == {prints[1].trade_id}


def test_percentile_mode_echo_carries_effective_threshold_and_estimated() -> None:
    rng = random.Random(3)  # noqa: S311 - seeded, reproducible test data
    cfg = BigTradeConfig(mode="percentile", value=Decimal("99"), percentile_window_ms=3_600_000)
    eng = BigTradeEngine("BTCUSDT", TICK, cfg)
    prints = [
        trade(i * 200_000, "100.0", f"{rng.lognormvariate(1, 1):.3f}") for i in range(1, 3000)
    ]
    out = eng.process(prints)
    echoes = [e for e in out if isinstance(e, BigTradeThresholdEvent)]
    assert echoes and all(e.estimated for e in echoes)
    last = echoes[-1]
    assert last.effective_threshold_abs > 0 and last.sample_count > 0
    flagged = [e for e in out if isinstance(e, BigTradeEvent)]
    assert flagged and all(e.estimated for e in flagged)


def test_threshold_echo_cadence_is_one_per_5s_print_time_boundary() -> None:
    eng = BigTradeEngine("BTCUSDT", TICK, BigTradeConfig())
    # 60 prints, one every 250 ms, spanning 15 s of print time -> 3 or 4 boundaries
    prints = [trade(10 * S + i * 250_000, "100.0", "1") for i in range(60)]
    echoes = [e for e in eng.process(prints) if isinstance(e, BigTradeThresholdEvent)]
    slots = [e.ts_event // (5 * S) for e in echoes]
    assert slots == sorted(set(slots))  # never two in one 5 s slot
    gaps = [b.ts_event - a.ts_event for a, b in pairwise(echoes)]
    assert all(g >= 250_000 for g in gaps) and len(echoes) == 3


def _overflag_engine() -> BigTradeEngine:
    return BigTradeEngine("BTCUSDT", TICK, BigTradeConfig(mode="absolute_size", value=Decimal("2")))


def _feed(eng: BigTradeEngine, big_every: int, n: int = 100) -> Sequence[object]:
    prints = [trade(S + i * 10_000, "100.0", "3" if i % big_every == 0 else "1") for i in range(n)]
    return eng.process(prints) + eng.process([trade(7 * S, "100.0", "1")])


def test_overflag_at_exactly_20_percent_does_not_cap() -> None:
    out = _feed(_overflag_engine(), big_every=5)  # exactly 20 / 100
    assert not any(isinstance(e, BigTradeAdvisoryEvent) for e in out)


def test_overflag_above_20_percent_emits_advisory_and_caps_but_keeps_emitting() -> None:
    eng = _overflag_engine()
    out = _feed(eng, big_every=4)  # 25 %
    adv = [e for e in out if isinstance(e, BigTradeAdvisoryEvent)]
    assert len(adv) == 1
    a = adv[0]
    assert a.reason == "threshold_too_low" and a.cap_active and a.threshold_abs == Decimal("2")
    assert a.flagged_fraction > Decimal("0.2") and a.suggested_value > 0
    echo = [e for e in out if isinstance(e, BigTradeThresholdEvent)][-1]
    assert echo.cap_active and echo.effective_threshold_abs >= Decimal("2")
    more = eng.process([trade(8 * S, "100.0", "3")])
    capped = [e for e in more if isinstance(e, BigTradeEvent)]
    assert capped and capped[0].capped  # never suppressed


def test_duplicate_trade_id_counted_once_in_thresholds_and_clusters() -> None:
    eng = BigTradeEngine(
        "BTCUSDT", TICK, BigTradeConfig(value=Decimal("100"), cluster_window_ms=250)
    )
    a = trade(S, "100.0", "2", trade_id="dup")
    out = eng.process([a]) + eng.process([a, trade(S + 1, "100.0", "2", trade_id="dup")])
    assert [e.trade_id for e in out if isinstance(e, BigTradeEvent)] == ["dup"]
    clusters = eng.flush()
    assert clusters[0].cluster_size == 1


@pytest.mark.parametrize(("price", "qty"), [("100.05", "1"), ("100.0", "0"), ("-100.0", "1")])
def test_input_assert_rejects_off_tick_and_non_positive(price: str, qty: str) -> None:
    eng = BigTradeEngine("BTCUSDT", TICK, BigTradeConfig(value=Decimal("0")))
    bad = trade(S, "100.0", "1").model_copy(update={"price": Decimal(price), "qty": Decimal(qty)})
    assert eng.process([bad]) == []


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"value": Decimal("-1")}, "value"),
        ({"value": Decimal("NaN")}, "value"),
        ({"mode": "percentile", "value": Decimal("100")}, "percentile"),
        ({"mode": "percentile", "value": Decimal("0")}, "percentile"),
        ({"percentile_window_ms": 59_999}, "percentile_window_ms"),
        ({"cluster_window_ms": 5001}, "cluster_window_ms"),
        ({"cluster_window_ms": -1}, "cluster_window_ms"),
        ({"cluster_tolerance_ticks": 21}, "cluster_tolerance_ticks"),
        ({"mode": "zscore"}, "mode"),
    ],
)
def test_config_bounds_rejected_before_allocation(kwargs: dict[str, object], field: str) -> None:
    with pytest.raises(BigTradeConfigInvalid, match=field):
        BigTradeConfig(**kwargs).validated()  # type: ignore[arg-type]  # bad values on purpose


def test_ws_surface_caps_cluster_window_at_2000() -> None:
    BigTradeConfig(cluster_window_ms=2000).validated(surface="ws")
    with pytest.raises(BigTradeConfigInvalid):
        BigTradeConfig(cluster_window_ms=2001).validated(surface="ws")
    BigTradeConfig(cluster_window_ms=5000).validated(surface="rest")


def test_reconfigure_closes_clusters_and_echoes_new_config() -> None:
    eng = BigTradeEngine("BTCUSDT", TICK, BigTradeConfig(value=Decimal("1"), cluster_window_ms=250))
    p = trade(S, "100.0", "1")
    eng.process([p])
    out = eng.reconfigure(BigTradeConfig(value=Decimal("1"), cluster_window_ms=1000), at=p)
    kinds = [type(e).__name__ for e in out]
    assert kinds == ["TradeClusterEvent", "BigTradeThresholdEvent"]
    assert out[0].close_reason == "config_change"  # type: ignore[union-attr]
    assert out[1].cluster_window_ms == 1000  # type: ignore[union-attr]


def test_replay_compares_and_does_not_republish() -> None:
    cfg = BigTradeConfig(mode="absolute_size", value=Decimal("2"))
    prints = [trade(S + i * 10_000, "100.0", "3" if i % 4 == 0 else "1") for i in range(100)]
    prints.append(trade(7 * S, "100.0", "1"))
    live = BigTradeEngine("BTCUSDT", TICK, cfg).process(prints)
    rec = [e for e in live if isinstance(e, BigTradeThresholdEvent | BigTradeAdvisoryEvent)]
    rep = BigTradeEngine("BTCUSDT", TICK, cfg, source="replay", recorded=rec)
    out = rep.process(prints)
    assert not any(isinstance(e, BigTradeThresholdEvent | BigTradeAdvisoryEvent) for e in out)
    assert rep.replay_mismatches == 0
    assert _flagged(out) == _flagged(live)


def test_replay_mismatch_is_counted() -> None:
    cfg = BigTradeConfig(mode="absolute_size", value=Decimal("2"))
    prints = [trade(S, "100.0", "1")]
    rec = [
        e
        for e in BigTradeEngine("BTCUSDT", TICK, cfg).process(prints)
        if isinstance(e, BigTradeThresholdEvent)
    ]
    bad = [rec[0].model_copy(update={"effective_threshold_abs": Decimal("9")})]
    rep = BigTradeEngine("BTCUSDT", TICK, cfg, source="replay", recorded=bad)
    rep.process(prints)
    rep.process([trade(20 * S, "100.0", "1")])  # second echo with nothing recorded
    assert rep.replay_mismatches == 2


def test_dedupe_ring_is_bounded_and_forgets_oldest(monkeypatch: pytest.MonkeyPatch) -> None:
    from candleviewer.orderflow import limits

    monkeypatch.setattr(limits, "DEDUPE_IDS_MAX", 2)
    eng = BigTradeEngine("BTCUSDT", TICK, BigTradeConfig(value=Decimal("0")))
    a, b, c = (trade(S + i, "100.0", "1", trade_id=f"r{i}") for i in range(3))
    eng.process([a, b, c])
    again = eng.process([trade(S + 9, "100.0", "1", trade_id="r0")])
    assert [e.trade_id for e in again if isinstance(e, BigTradeEvent)] == ["r0"]


def test_all_equal_notional_stream_flags_all_at_threshold_and_caps() -> None:
    eng = BigTradeEngine("BTCUSDT", TICK, BigTradeConfig(mode="notional", value=Decimal("100")))
    out = eng.process([trade(S + i * 10_000, "100.0", "1") for i in range(100)])
    out += eng.process([trade(6 * S, "100.0", "1")])
    assert len([e for e in out if isinstance(e, BigTradeEvent)]) == 101  # never suppressed
    assert any(isinstance(e, BigTradeAdvisoryEvent) for e in out)


def test_monotone_notional_stream_percentile_threshold_rises() -> None:
    cfg = BigTradeConfig(mode="percentile", value=Decimal("90"))
    eng = BigTradeEngine("BTCUSDT", TICK, cfg)
    prints = [trade(S + i * 50_000, "100.0", f"{1 + i / 100:.2f}") for i in range(1000)]
    echoes = [e for e in eng.process(prints) if isinstance(e, BigTradeThresholdEvent)]
    levels = [e.effective_threshold_abs for e in echoes if e.sample_count]
    assert levels == sorted(levels) and levels[-1] > levels[0]


def test_percentile_at_or_below_80_is_never_capped() -> None:
    eng = BigTradeEngine("BTCUSDT", TICK, BigTradeConfig(mode="percentile", value=Decimal("50")))
    prints = [trade(S + i * 10_000, "100.0", f"{1 + (i % 10)}") for i in range(2000)]
    out = eng.process(prints)
    assert not any(isinstance(e, BigTradeAdvisoryEvent) for e in out)
    echoes = [e for e in out if isinstance(e, BigTradeThresholdEvent)]
    assert echoes and not any(e.cap_active for e in echoes)


def test_cap_reentry_emits_a_fresh_advisory() -> None:
    """Leaving the cap and re-entering is a new episode -> a fresh advisory (documented)."""
    cfg = BigTradeConfig(mode="absolute_size", value=Decimal("2"), percentile_window_ms=60_000)
    eng = BigTradeEngine("BTCUSDT", TICK, cfg)
    big = [trade(S + i * 10_000, "100.0", "3") for i in range(50)]  # 100 % flagged
    calm = [trade(70 * S + i * 10_000, "100.0", "1") for i in range(1000)]  # 60 s rolled
    again = [trade(200 * S + i * 10_000, "100.0", "3") for i in range(50)]  # calm rolled out
    tail = [trade(210 * S, "100.0", "3")]
    out = [*eng.process(big), *eng.process([trade(10 * S, "100.0", "3")])]
    out += [*eng.process(calm), *eng.process([trade(85 * S, "100.0", "1")])]
    out += [*eng.process(again), *eng.process(tail)]
    advisories = [e for e in out if isinstance(e, BigTradeAdvisoryEvent)]
    caps = [e.cap_active for e in out if isinstance(e, BigTradeThresholdEvent)]
    assert len(advisories) == 2 and True in caps and False in caps


def test_batch_split_exactly_on_5s_boundary_print_is_deterministic() -> None:
    cfg = BigTradeConfig(mode="percentile", value=Decimal("95"), cluster_window_ms=250)
    prints = [trade(4 * S + i * 100_000, "100.0", f"{1 + i % 7}") for i in range(30)]
    boundary = next(i for i, p in enumerate(prints) if p.ts_event == 5 * S)
    whole = BigTradeEngine("BTCUSDT", TICK, cfg)
    a = [*whole.process(prints), *whole.flush()]
    split = BigTradeEngine("BTCUSDT", TICK, cfg)
    b = [*split.process(prints[:boundary]), *split.process(prints[boundary:]), *split.flush()]
    c_eng = BigTradeEngine("BTCUSDT", TICK, cfg)
    c = [*c_eng.process(prints[: boundary + 1]), *c_eng.process(prints[boundary + 1 :])]
    c += c_eng.flush()
    assert [e.model_dump_json() for e in a] == [e.model_dump_json() for e in b]
    assert [e.model_dump_json() for e in a] == [e.model_dump_json() for e in c]
