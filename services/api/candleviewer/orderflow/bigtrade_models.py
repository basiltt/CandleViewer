"""Big-trade internal events and engine config (24-internal-schemas §2.10, E22-T01).

The shapes are the binding contract; do not change a field without bumping `schema_version`
(§17). Config bounds come only from `orderflow/limits.py` (E22 threat model §7)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from candleviewer.domain.events import MarketEvent
from candleviewer.domain.primitives import Notional, Px, Qty, Side, Ticks, TsUs
from candleviewer.orderflow import limits as L
from candleviewer.orderflow.errors import OrderflowError

Mode = Literal["absolute_size", "notional", "percentile"]
CloseReason = Literal["deadline", "superseded", "evicted", "config_change", "flush"]


class BigTradeConfigInvalid(OrderflowError):
    """A config value outside the SR-E22-04 / §3 bounds (rejected before any allocation)."""


@dataclass(frozen=True, slots=True)
class BigTradeConfig:
    """Per-symbol config; one vocabulary with 23-ws §6.1. `value` is base units
    (absolute_size), USDT (notional) or 0..100 exclusive (percentile)."""

    mode: Mode = "notional"
    value: Decimal = Decimal("250000")
    percentile_window_ms: int = 3_600_000
    cluster_window_ms: int = 0  # 0 disables clustering
    cluster_tolerance_ticks: int = 0

    def validated(self, *, surface: Literal["rest", "ws"] = "rest") -> BigTradeConfig:
        cap = L.CLUSTER_WINDOW_MS_MAX_WS if surface == "ws" else L.CLUSTER_WINDOW_MS_MAX_REST
        checks = (
            (self.mode in ("absolute_size", "notional", "percentile"), "mode"),
            (self.value.is_finite() and self.value >= 0, "value"),
            (self.mode != "percentile" or 0 < self.value < 100, "percentile"),
            (
                L.PERCENTILE_WINDOW_MS_MIN
                <= self.percentile_window_ms
                <= L.PERCENTILE_WINDOW_MS_MAX,
                "percentile_window_ms",
            ),
            (0 <= self.cluster_window_ms <= cap, "cluster_window_ms"),
            (
                0 <= self.cluster_tolerance_ticks <= L.CLUSTER_TOLERANCE_TICKS_MAX,
                "cluster_tolerance_ticks",
            ),
        )
        for ok, field in checks:
            if not ok:
                raise BigTradeConfigInvalid(field)
        return self


class BigTradeEvent(MarketEvent):
    trade_id: str
    price: Px
    qty: Qty
    side: Side
    notional: Notional
    price_ticks: Ticks
    mode: Mode
    threshold_abs: Decimal
    capped: bool
    estimated: bool
    seq: int


class TradeClusterEvent(MarketEvent):
    cluster_id: str
    side: Side
    price_bucket: int
    anchor_price: Px
    first_ts_event: TsUs
    last_ts_event: TsUs
    trade_id_count: int
    first_trade_id: str
    last_trade_id: str
    trade_ids: tuple[str, ...]
    trade_ids_truncated: bool
    cluster_size: int
    total_qty: Qty
    total_notional: Notional
    vwap: Px
    max_print_qty: Qty
    close_reason: CloseReason
    estimated: Literal[True] = True

    def bar_open_us(self, bar_interval_us: int) -> TsUs:
        """US-BIG-004 sc.3: a cluster belongs to the bar containing its FIRST print."""
        return self.first_ts_event - self.first_ts_event % bar_interval_us


class BigTradeThresholdEvent(MarketEvent):
    mode: Mode
    value: Decimal
    percentile_window_ms: int
    cluster_window_ms: int
    cluster_tolerance_ticks: int
    effective_threshold_abs: Decimal
    cap_active: bool
    sample_count: int
    flagged_fraction: Decimal
    estimated: bool


class BigTradeAdvisoryEvent(MarketEvent):
    reason: Literal["threshold_too_low"]
    mode: Mode
    threshold_abs: Decimal
    flagged_fraction: Decimal
    suggested_value: Decimal
    cap_active: bool


BigTradeOutput = BigTradeEvent | TradeClusterEvent | BigTradeThresholdEvent | BigTradeAdvisoryEvent

TOPIC_DETAIL: dict[type[MarketEvent], str] = {
    BigTradeEvent: "bigtrade",
    TradeClusterEvent: "cluster",
    BigTradeThresholdEvent: "bigtrade-threshold",
    BigTradeAdvisoryEvent: "bigtrade-advisory",
}
