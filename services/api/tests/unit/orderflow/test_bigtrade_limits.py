"""E22 threat model §7 test 1: every bound in `orderflow/limits.py` asserted verbatim.

Changing a value means editing this test too — a reviewed diff under the CODEOWNERS rule
on `orderflow/limits.py` (backend + security)."""

from __future__ import annotations

from decimal import Decimal

from candleviewer.orderflow import limits as L


def test_limits_threat_model_constants_verbatim() -> None:
    assert L.TRADES_MAX_WINDOW_MS == 6 * 3600 * 1000
    assert L.TRADES_MAX_WINDOW_CLUSTERED_MS == 15 * 60 * 1000
    assert L.TRADES_MAX_LIMIT == 500
    assert (L.CLUSTER_WINDOW_MS_MAX_REST, L.CLUSTER_WINDOW_MS_MAX_WS) == (5000, 2000)
    assert L.CLUSTER_TOLERANCE_TICKS_MAX == 20
    assert (L.CLUSTER_KEYS_MAX, L.PRINTS_BUFFER_MAX) == (4096, 16384)
    assert (L.TRADES_SUBS_PER_USER_MAX, L.CONNECTIONS_PER_USER_MAX) == (60, 8)
    assert L.OPTION_SETS_PER_SYMBOL_MAX == 2
    assert (L.CONN_BUDGET_FRAMES, L.CONN_BUDGET_BYTES) == (2000, 8 * 1024 * 1024)
    assert Decimal("0.5") == L.TRADES_BUDGET_SHARE
    assert (L.RING_BUFFER_MAX_PRINTS, L.RING_BUFFER_MAX_BYTES) == (50_000, 32 * 1024 * 1024)
    assert L.VISIBLE_BUBBLES_MAX == 5000
    assert L.BUBBLE_FLASH_MAX_HZ == 3
    assert L.THRESHOLD_SYMBOLS_PER_USER_MAX == 200


def test_limits_contract_2_10_constants_verbatim() -> None:
    assert L.CLUSTER_IDS_MAX == 64
    assert L.PRINTS_PER_MS_BUDGET == 5
    assert L.THRESHOLD_REFRESH_US == 5_000_000
    assert Decimal("0.20") == L.OVERFLAG_FRACTION
    assert L.OVERFLAG_CAP_QUANTILE == 0.80
    assert L.OVERFLAG_MIN_SAMPLES == 20
    assert L.PERCENTILE_WINDOW_BUCKETS == 12
    assert (L.PERCENTILE_WINDOW_MS_MIN, L.PERCENTILE_WINDOW_MS_MAX) == (60_000, 86_400_000)
    assert L.DEDUPE_IDS_MAX == 50_000


def test_prints_buffer_effective_max_floor_and_scaling() -> None:
    assert L.prints_buffer_effective_max(0) == 16384
    assert L.prints_buffer_effective_max(2000) == 16384
    assert L.prints_buffer_effective_max(5000) == 25_000


def test_min_size_floor_is_max_of_lot_and_tick_notional() -> None:
    assert L.min_size_floor(Decimal("0.001"), Decimal("6.3")) == Decimal("6.3")
    assert L.min_size_floor(Decimal("10"), Decimal("6.3")) == Decimal("10")
