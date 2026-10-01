"""Bybit v5 `tickers.{symbol}` frame parsing (E08-S03, C-2.2: venue vocabulary
stays in `exchange/bybit/`).

Mapping per `docs/plan/24-internal-schemas.md` §2.3. The linear stream is
delta-encoded: only changed keys are present. Empty-string values are treated
as absent (Bybit uses them for "no value", e.g. an empty book side) so they can
never null out a previously known field. An explicit `"0"` is a real value.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

from candleviewer.exchange.base.ticker_delta import TickerDelta

TOPIC_PREFIX = "tickers."
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{4,20}$")

_WIRE_TO_FIELD: dict[str, str] = {
    "lastPrice": "last_price",
    "markPrice": "mark_price",
    "indexPrice": "index_price",
    "bid1Price": "bid1_price",
    "bid1Size": "bid1_qty",
    "ask1Price": "ask1_price",
    "ask1Size": "ask1_qty",
    "openInterest": "open_interest",
    "openInterestValue": "open_interest_value",
    "turnover24h": "turnover_24h",
    "volume24h": "volume_24h",
    "price24hPcnt": "price_24h_pcnt",
    "fundingRate": "funding_rate",
}


def ticker_topic(symbol: str) -> str:
    return f"{TOPIC_PREFIX}{symbol}"


def parse_ticker_frame(frame: str) -> TickerDelta | None:
    """Parse one raw WS frame. `None` for non-ticker frames (acks, pongs, other
    topics); `ValueError` for a ticker frame that is malformed."""
    try:
        msg = json.loads(frame)
    except ValueError:
        return None
    if not isinstance(msg, dict):
        return None
    topic = msg.get("topic")
    if not isinstance(topic, str) or not topic.startswith(TOPIC_PREFIX):
        return None
    symbol = topic[len(TOPIC_PREFIX) :]
    if not _SYMBOL_RE.match(symbol):
        raise ValueError("ticker frame carries an invalid symbol")
    kind, data, ts = msg.get("type"), msg.get("data"), msg.get("ts")
    if kind not in ("snapshot", "delta") or not isinstance(data, dict):
        raise ValueError("ticker frame missing type/data")
    if not isinstance(ts, int) or isinstance(ts, bool) or ts <= 0:
        raise ValueError("ticker frame missing envelope ts")
    fields: dict[str, Decimal | int] = {}
    try:
        for wire, name in _WIRE_TO_FIELD.items():
            raw = data.get(wire)
            if raw is None or raw == "":
                continue
            value = Decimal(str(raw))
            if not value.is_finite():
                raise ValueError("non-finite ticker value")
            fields[name] = value
        nft = data.get("nextFundingTime")
        if nft not in (None, ""):
            fields["next_funding_time"] = int(str(nft)) * 1000  # ms -> µs
    except InvalidOperation as exc:
        raise ValueError("unparseable ticker value") from exc
    return TickerDelta(symbol, kind == "snapshot", ts * 1000, fields)
