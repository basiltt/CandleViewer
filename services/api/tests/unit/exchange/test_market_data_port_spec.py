"""E08-T01 acceptance criteria (ticket body, `docs/plan/backlog/all-tickets.json`
key `E08-T01`), transcribed verbatim from the Gherkin as one test per
scenario.

Scenario 1 "Port matches the specification" is `test_market_data_port_matches_spec`.
Scenario 2 "Fake adapter satisfies the protocol" is `test_fake_exchange_satisfies_market_data_port`.
Scenario 4 "Unmapped exchange error" is in `test_unmapped_error.py` (separate
file — it needs its own boundary-wrapper helper). Scenario 3 "Leak of
exchange vocabulary fails CI" is `scripts/tests/test_lint_exchange_vocabulary.py`
(a CI-facing script test, not an in-process one, since P3/L1 runs as a
subprocess-style check over the whole tree).
"""

from __future__ import annotations

import inspect
from typing import Protocol

from candleviewer.exchange.base import MarketDataPort
from candleviewer.exchange.base.ports import MarketDataPort as _MarketDataPortDirect

# The exact method names §14.1 declares on MarketDataPort, verbatim from
# `docs/plan/24-internal-schemas.md` Sec.14.1. Any drift here — a renamed,
# removed or added method on the shipped protocol — must fail this test
# (acceptance criterion 1).
_SPEC_METHOD_NAMES = frozenset(
    {
        "instruments",
        "instrument",
        "subscribe_trades",
        "subscribe_book",
        "subscribe_ticker",
        "subscribe_klines",
        "subscribe_liquidations",
        "fetch_klines",
        "fetch_recent_trades",
        "fetch_orderbook",
        "fetch_open_interest",
        "fetch_funding_history",
        "fetch_risk_limits",
        "server_time_us",
    }
)


def test_market_data_port_is_the_same_object_reexported() -> None:
    """`candleviewer.exchange.base.MarketDataPort` (the public surface) must
    be the identical `Protocol` object defined in `ports.py`, not a
    reimplementation that could silently drift from it."""
    assert MarketDataPort is _MarketDataPortDirect


def test_market_data_port_matches_spec_method_set() -> None:
    """Acceptance criterion 1: the declared method *names* on
    `MarketDataPort` are exactly the §14.1 set — no more, no fewer."""
    declared = {
        name
        for name, member in inspect.getmembers(MarketDataPort)
        if not name.startswith("_") and callable(member)
    }
    assert declared == _SPEC_METHOD_NAMES


def test_market_data_port_is_a_runtime_checkable_protocol() -> None:
    assert issubclass(MarketDataPort, Protocol)  # type: ignore[arg-type]
    assert getattr(MarketDataPort, "_is_runtime_protocol", False) is True


def test_market_data_port_methods_are_all_coroutines_or_async_generators() -> None:
    """Every §14.1 method is declared `async def` (plain `async def` for
    `fetch_*`/scalar reads, async-generator for `subscribe_*`) — a
    synchronous method here would violate the async-only backend rule
    (`.claude/rules/20-python-backend.md`)."""
    for name in _SPEC_METHOD_NAMES:
        member = inspect.getattr_static(MarketDataPort, name)
        # Protocol methods are plain functions on the class; check the
        # underlying function is a coroutine function or async generator.
        assert inspect.iscoroutinefunction(member) or inspect.isasyncgenfunction(member), (
            f"{name} must be declared async"
        )
