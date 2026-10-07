"""Kline backfill domain errors shared by the adapter, ingestion and bars (E12-S05).

`KlinePageRejected` lives here (not in the concrete adapter) so `ingestion` can tell a rejected
page from a transient failure without importing the adapter (C-3.1), mirroring
`domain.funding.FundingRowRejected`.
"""

from __future__ import annotations

from typing import Final

#: Bounded `reason` values (safe as a metric label) for a rejected kline page (SR-E12-09).
REJECT_REASONS: Final = (
    "envelope",
    "row_shape",
    "unparseable",
    "non_monotonic",
    "misaligned_time",
    "high_below_body",
    "low_above_body",
    "non_positive_price",
    "negative_volume",
    "off_tick",
    "symbol_mismatch",
)


class KlinePageRejected(ValueError):
    """A whole `/v5/market/kline` page failed strict validation (SR-E12-09, BR-02).

    The page is rejected as a unit (never row-by-row): a partially plausible page from a
    tampered response must not leak into `bars_time`. Prior pages stay persisted.
    """

    def __init__(self, message: str, reason: str = "envelope") -> None:
        super().__init__(message)
        self.reason = reason if reason in REJECT_REASONS else "envelope"


__all__ = ["REJECT_REASONS", "KlinePageRejected"]
