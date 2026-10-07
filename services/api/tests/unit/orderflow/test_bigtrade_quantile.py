"""P² + trimmed wrapper + bucketed trailing window (SR-E22-14, 24-internal-schemas §2.10)."""

from __future__ import annotations

import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.orderflow.quantile import P2Quantile, WindowedQuantiles
from tests.unit.orderflow._bigtrade_helpers import recorded_prints


def _rank_error(values: list[float], estimate: float, q: float) -> float:
    below = sum(1 for v in values if v <= estimate)
    return abs(below / len(values) - q)


@settings(max_examples=25, deadline=None)
@given(seed=st.integers(0, 10_000), q=st.sampled_from([0.5, 0.8, 0.9, 0.99]))
def test_p2_rank_error_within_one_percent_on_seeded_lognormal(seed: int, q: float) -> None:
    rng = random.Random(seed)  # noqa: S311 - seeded, reproducible test data
    values = [rng.lognormvariate(8.0, 1.2) for _ in range(5000)]
    est = P2Quantile(q)
    for v in values:
        est.add(v)
    assert est.count == 5000
    assert _rank_error(values, est.value(), q) <= 0.01


def test_p2_rank_error_on_recorded_notionals() -> None:
    """Recorded distribution (E08-T05 corpus, CORPUS path via tests._corpus)."""
    values = [float(p.price * p.qty) for p in recorded_prints("BTCUSDT")]
    for q in (0.5, 0.8, 0.99):
        est = P2Quantile(q)
        for v in values:
            est.add(v)
        assert _rank_error(values, est.value(), q) <= 0.01


def test_p2_small_counts_are_exact_order_statistics() -> None:
    est = P2Quantile(0.5)
    assert est.count == 0
    for v in (3.0, 1.0, 2.0):
        est.add(v)
    assert est.markers() == [(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)]


@settings(max_examples=20, deadline=None)
@given(seed=st.integers(0, 10_000), q=st.sampled_from([0.8, 0.99]))
def test_windowed_merge_rank_error_within_one_percent(seed: int, q: float) -> None:
    """Bucket-aligned window: the exact quantile is over the prints of the kept buckets."""
    rng = random.Random(seed)  # noqa: S311 - seeded, reproducible test data
    w = WindowedQuantiles(q, window_us=3_600_000_000, buckets=12)
    seen: list[tuple[int, float]] = []
    ts = 0
    for _ in range(12_000):
        ts += rng.randint(100_000, 600_000)
        v = rng.lognormvariate(9.0, 1.0)
        w.add(ts, v, flagged=False)
        seen.append((ts, v))
    w.expire(ts)
    sample = [v for t, v in seen if t >= w.oldest_ts_us()]
    assert len(sample) == w.count
    est = w.quantile(primary=True)
    assert est is not None
    assert _rank_error(sample, est, q) <= 0.01


def test_trimmed_wrapper_single_outlier_does_not_move_threshold() -> None:
    rng = random.Random(7)  # noqa: S311 - seeded, reproducible test data
    base = [rng.lognormvariate(8.0, 0.5) for _ in range(2000)]
    a = WindowedQuantiles(0.99, window_us=60_000_000, buckets=1)
    b = WindowedQuantiles(0.99, window_us=60_000_000, buckets=1)
    for i, v in enumerate(base):
        a.add(i, v, flagged=False)
        b.add(i, v, flagged=False)
    b.add(len(base), 1e15, flagged=False)
    a.add(len(base), base[0], flagged=False)
    qa, qb = a.quantile(primary=True), b.quantile(primary=True)
    assert qa is not None and qb is not None
    assert qb == pytest.approx(qa, rel=0.02)
    # winsorised: the max marker is clamped, not 1e15 (SR-E22-14)
    assert b.max_marker() < 1e15


def test_p2_trim_factor_clamps_extreme_input() -> None:
    est = P2Quantile(0.5, trim_factor=10.0)
    for v in range(1, 101):
        est.add(float(v))
    upper_middle = est.markers()[-2][0]
    est.add(1e9)
    assert est.markers()[-1][0] <= 10.0 * upper_middle


def test_p2_rejects_out_of_range_quantile() -> None:
    with pytest.raises(ValueError, match="quantile"):
        P2Quantile(1.0)
    with pytest.raises(ValueError, match="buckets"):
        WindowedQuantiles(0.5, window_us=1_000, buckets=0)


def test_windowed_expiry_drops_old_buckets_and_flagged_fraction() -> None:
    w = WindowedQuantiles(0.9, window_us=12_000_000, buckets=12)
    for i in range(10):
        w.add(i * 1_000_000, float(i + 1), flagged=i < 5)
    assert w.count == 10 and w.flagged == 5
    w.expire(30_000_000)
    assert w.count == 0 and w.flagged == 0
    assert w.quantile(primary=True) is None


def test_windowed_secondary_estimator_tracks_p80() -> None:
    w = WindowedQuantiles(0.99, window_us=60_000_000, buckets=4)
    for i in range(1, 1001):
        w.add(i, float(i), flagged=False)
    p80 = w.quantile(primary=False)
    assert p80 is not None and 780 <= p80 <= 820


@pytest.mark.parametrize("q", [0.5, 0.8, 0.99])
def test_p2_monotone_increasing_stream_rank_error_within_one_percent(q: float) -> None:
    values = [float(v) for v in range(1, 5001)]
    est = P2Quantile(q)
    for v in values:
        est.add(v)
    assert _rank_error(values, est.value(), q) <= 0.01


@pytest.mark.parametrize("q", [0.5, 0.99])
def test_p2_monotone_decreasing_stream_rank_error_within_one_percent(q: float) -> None:
    values = [float(v) for v in range(5000, 0, -1)]
    est = P2Quantile(q)
    for v in values:
        est.add(v)
    assert _rank_error(values, est.value(), q) <= 0.01


def test_all_equal_stream_returns_that_value_single_and_windowed() -> None:
    est = P2Quantile(0.99)
    w = WindowedQuantiles(0.99, window_us=60_000_000, buckets=4)
    for i in range(3000):
        est.add(250.0)
        w.add(i * 10_000, 250.0, flagged=False)
    assert est.value() == 250.0
    assert w.quantile(primary=True) == 250.0
    assert w.quantile(primary=False) == 250.0


def test_window_without_primary_tracks_only_cap_quantile() -> None:
    w = WindowedQuantiles(None, window_us=60_000_000, buckets=4)
    for i in range(1, 1001):
        w.add(i, float(i), flagged=False)
    assert w.quantile(primary=True) is None
    p80 = w.quantile(primary=False)
    assert p80 is not None and 780 <= p80 <= 820


def test_slot_aligned_window_covers_between_window_minus_width_and_window() -> None:
    w = WindowedQuantiles(0.5, window_us=3_600_000_000, buckets=12)  # 5 min slots
    now = 7_380_000_000  # 2 h 3 min
    w.expire(now)
    covered = now - w.oldest_ts_us()
    assert 3_600_000_000 - w.width <= covered <= 3_600_000_000
