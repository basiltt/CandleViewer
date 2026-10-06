"""E24-T02: funding-history REST pages -> settled series (8 h and 4 h symbols).

Pins what the adapter boundary owns: wire ordering (newest first), the settlement
cadence implied by each recorded symbol, and that every row survives strict
validation. The interval itself is never read from these payloads - the exchange
does not send one; it comes from the instruments cache.
"""

from __future__ import annotations

import itertools

import pytest

from candleviewer.exchange.bybit.funding import parse_funding_page
from tests._corpus import rest

CASES = (
    ("rest/funding_history_BTCUSDT_8h.json", "BTCUSDT", 8 * 3_600_000_000),
    ("rest/funding_history_ETHUSDT_4h.json", "ETHUSDT", 4 * 3_600_000_000),
)


@pytest.mark.parametrize(("rel", "symbol", "step_us"), CASES)
def test_funding_history_page_is_newest_first_at_the_symbols_cadence(
    rel: str, symbol: str, step_us: int
) -> None:
    rows = parse_funding_page(rest(rel), symbol=symbol)
    assert len(rows) == 4
    assert all(a.ts_us - b.ts_us == step_us for a, b in itertools.pairwise(rows))
    assert {r.symbol for r in rows} == {symbol}
