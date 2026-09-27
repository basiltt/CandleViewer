"""exchange.base module (M3).

ExchangeAdapter interface, normalised domain events, error taxonomy.

Public interface only — internal implementation modules are not re-exported.
Allowed dependencies (CONSTITUTION.md C-3.1): M1.

`Trade`/`Ticker` (E02-T12) are the first normalised domain event shapes; the
full `ExchangeAdapter` interface and error taxonomy land with E08.
"""

from __future__ import annotations

from candleviewer.exchange.base.models import Ticker, Trade, TradeSide

__all__: list[str] = ["Ticker", "Trade", "TradeSide"]
