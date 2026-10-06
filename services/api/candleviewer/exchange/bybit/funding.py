"""Bybit v5 settled funding history (`GET /v5/market/funding/history`, E24-T02).

All wire knowledge for the endpoint lives here (C-2.2): params, the
`fundingRate` / `fundingRateTimestamp` row shape, and strict validation. The
endpoint pages by *time window*, newest first (`endTime` walks backwards), not
by an opaque cursor; `limit` is 1-200. Public data only, no credentials.

Every row is validated before anything is returned; one malformed row rejects
the whole page (`FundingRowRejected`) so a spoofed or drifted upstream shape is
never partially accepted (STRIDE D1, `docs/security/threat-models/E24-derivatives.md`).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from candleviewer.domain.funding import FundingSettlement
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.rest import BybitRestClient

PATH: Final = "/v5/market/funding/history"
MAX_PAGE_LIMIT: Final = 200
#: Funding rates are fractions per interval; the exchange caps them far below 100 %.
MAX_ABS_RATE: Final = Decimal(1)
_SYMBOL_RE: Final = re.compile(r"^[A-Z0-9]{2,24}$")


class FundingRowRejected(ValueError):
    """A funding-history row (or its envelope) failed strict validation."""


def parse_funding_page(payload: dict[str, Any], *, symbol: str) -> list[FundingSettlement]:
    """Validate and normalise one page. Raises `FundingRowRejected`."""
    result = payload.get("result")
    if not isinstance(result, dict):
        raise FundingRowRejected("funding history: missing result object")
    rows = result.get("list")
    if not isinstance(rows, list):
        raise FundingRowRejected("funding history: missing list")
    out: list[FundingSettlement] = []
    for row in rows:
        if not isinstance(row, dict):
            raise FundingRowRejected("funding history: row is not an object")
        if row.get("symbol") != symbol:
            raise FundingRowRejected("funding history: row symbol does not match the request")
        raw_rate, raw_ts = row.get("fundingRate"), row.get("fundingRateTimestamp")
        if not isinstance(raw_rate, str) or not isinstance(raw_ts, str):
            raise FundingRowRejected(
                "funding history: fundingRate/fundingRateTimestamp not strings"
            )
        try:
            rate = Decimal(raw_rate)
            ts_ms = int(raw_ts)
        except (InvalidOperation, ValueError) as exc:
            raise FundingRowRejected("funding history: unparseable rate or timestamp") from exc
        if not rate.is_finite() or abs(rate) > MAX_ABS_RATE:
            raise FundingRowRejected("funding history: implausible funding rate")
        if ts_ms <= 0:
            raise FundingRowRejected("funding history: non-positive settlement time")
        out.append(FundingSettlement(ts_us=ts_ms * 1000, symbol=symbol, funding_rate=rate))
    return out


async def fetch_funding_page(
    client: BybitRestClient,
    symbol: str,
    *,
    start_us: int,
    end_us: int,
    limit: int = MAX_PAGE_LIMIT,
) -> list[FundingSettlement]:
    """One page (newest first) of settlements within `[start_us, end_us]`."""
    if not _SYMBOL_RE.match(symbol):
        raise FundingRowRejected("funding history: invalid symbol")
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        raise ValueError(f"limit must be within 1..{MAX_PAGE_LIMIT}")
    payload = await client.get_public(
        PATH,
        params={
            "category": "linear",
            "symbol": symbol,
            "startTime": start_us // 1000,
            "endTime": end_us // 1000,
            "limit": limit,
        },
        endpoint_class=EndpointClass.MARKET_DATA,
    )
    return parse_funding_page(payload, symbol=symbol)


class BybitFundingFetcher:
    """`orderflow.funding.FundingFetcher` over the governed REST client. Uses the
    `MARKET_DATA` bucket, so a backfill can never draw down the stop/cancel/SL
    reserve of the order or position buckets (C-12.7)."""

    def __init__(self, client: BybitRestClient) -> None:
        self._client = client

    async def __call__(
        self, symbol: str, start_us: int, end_us: int, limit: int
    ) -> Sequence[FundingSettlement]:
        return await fetch_funding_page(
            self._client, symbol, start_us=start_us, end_us=end_us, limit=limit
        )


__all__ = [
    "MAX_PAGE_LIMIT",
    "PATH",
    "BybitFundingFetcher",
    "FundingRowRejected",
    "fetch_funding_page",
    "parse_funding_page",
]
