"""E40-K01 harness tests: the measurement code itself must be deterministic and correct."""

from __future__ import annotations

from benchmarks.alerts.extras import (
    bar_open,
    guard_cost,
    late_tick_report,
    notify_only,
    once_per_bar_fires,
    storm_histogram,
)
from benchmarks.alerts.harness import corpus, run_option

DAY = 86_400_000


def test_both_options_deliver_identically_and_dedup_collapses_subscriptions() -> None:
    """Scenario: both options measured under the identical stream; Q2 subscription count."""
    alerts = corpus(40, 6)
    shared = run_option("shared", alerts, 400)
    dedup = run_option("shared_dedup", alerts, 400)
    sep = run_option("separate", alerts, 400)
    assert shared.deliveries == dedup.deliveries == sep.deliveries
    assert shared.subscriptions == 40
    assert dedup.subscriptions == sep.subscriptions == 6


def test_bar_open_is_stable_under_late_ticks_for_all_timeframes() -> None:
    """Q4: a late tick inside the bar maps to the same key."""
    for tf, size in (("1m", 60_000), ("15m", 900_000), ("4h", 14_400_000), ("1d", DAY)):
        base = 1_700_000_000_000 // size * size
        assert bar_open(base + 1, tf) == bar_open(base + size - 1, tf) == base


def test_weekly_bar_opens_on_monday_utc() -> None:
    monday = 1_700_438_400_000  # 2023-11-20T00:00Z
    assert bar_open(monday + 3 * DAY, "1w") == monday


def test_storm_histogram_is_seeded_and_notify_guard_rejects_actions() -> None:
    assert storm_histogram(seed=1) == storm_histogram(seed=1)
    assert notify_only({"actions": [{"type": "send_notification"}]}) == []
    assert notify_only({"actions": [{"type": "place_order"}]}) == ["place_order"]
    assert guard_cost(50)["p99_ms"] < 300


def test_late_tick_revising_a_closed_bar_fires_once_for_every_timeframe() -> None:
    """Q4: a bar revised by a late tick keeps its key; no double fire, no new key."""
    rep = late_tick_report()
    assert len(rep) == 12
    assert all(v["ok"] for v in rep.values()), rep
    assert once_per_bar_fires([(1, 10), (2, 10), (59_999, 10)], "1m", 10) == [0]
