"""E08-Q02 group 2 (precision & filter validation): E08-TC-B01, E08-TC-B02, E08-TC-B03,
E08-TC-B04, E08-TC-B05, E08-TC-B06, E08-TC-B07.

Recorded `instruments-info` rows -> `parse_instruments` -> the shared `InstrumentPolicy` (the one
rule source of US-MKT-004). Asserts the typed violation codes, the round-down / nearest rounding
and that the shared golden vectors give identical verdicts through the *recorded* catalogue.
The client half of B01/B04/B07 is E08-Q05.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.domain.events import Instrument
from candleviewer.exchange.base.errors import InstrumentFilterError
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.exchange.policy import FilterViolationCode as V
from candleviewer.exchange.policy import InstrumentPolicy
from tests._corpus import CORPUS_ROOT, rest

FETCHED_US = 1_700_000_000_000_000
GOLDEN = CORPUS_ROOT.parent / "golden" / "policy" / "corpus.json"


def _catalogue(rel: str) -> dict[str, Instrument]:
    res = parse_instruments(list(rest(rel)["result"]["list"]), fetched_at_us=FETCHED_US)
    assert not res.rejected
    return {i.symbol: i for i in res.instruments}


def _btc() -> InstrumentPolicy:
    return InstrumentPolicy(_catalogue("rest/instruments_before.json")["BTCUSDT"])


def _codes(policy: InstrumentPolicy, price: str, qty: str) -> set[V]:
    return {v.code for v in policy.validate(Decimal(price), Decimal(qty))}


def test_b01_price_off_the_tick_grid_is_typed_and_snaps_to_nearest_tick() -> None:
    """E08-TC-B01: 65000.03 on a 0.10 tick -> PRICE_NOT_TICK_MULTIPLE; snaps to 65000.0."""
    p = _btc()
    assert _codes(p, "65000.03", "0.010") == {V.PRICE_NOT_TICK_MULTIPLE}
    assert p.round_price(Decimal("65000.03")) == Decimal("65000.0")
    assert _codes(p, "65000.00", "0.010") == set()  # the snapped value is clean


def test_b02_qty_off_the_lot_grid_is_typed_and_rounds_down_never_up() -> None:
    """E08-TC-B02: 0.0015 -> QTY_NOT_LOT_MULTIPLE; rounded DOWN to 0.001."""
    p = _btc()
    assert _codes(p, "65000.0", "0.0015") == {V.QTY_NOT_LOT_MULTIPLE}
    assert p.round_qty(Decimal("0.0015")) == Decimal("0.001")
    assert p.round_qty(Decimal("0.0019")) == Decimal("0.001")


def test_b03_qty_below_the_minimum_is_typed() -> None:
    """E08-TC-B03: 0.0005 < minOrderQty 0.001 -> QTY_BELOW_MIN."""
    assert V.QTY_BELOW_MIN in _codes(_btc(), "65000.0", "0.0005")


def test_b04_qty_above_the_maximum_is_typed_and_names_the_limit() -> None:
    """E08-TC-B04: 101 > maxOrderQty 100 -> QTY_ABOVE_MAX with the limit in the text."""
    violations = _btc().validate(Decimal("100.0"), Decimal("101"))
    (v,) = violations
    assert v.code is V.QTY_ABOVE_MAX and "100" in v.user_message


def test_b05_notional_below_the_minimum_is_typed() -> None:
    """E08-TC-B05: price 1000.0 x qty 0.001 = 1 < minNotionalValue 5 -> NOTIONAL_BELOW_MIN."""
    assert _codes(_btc(), "1000.0", "0.001") == {V.NOTIONAL_BELOW_MIN}


def test_b06_closed_symbol_is_not_trading_and_enforce_raises() -> None:
    """E08-TC-B06: the recorded delisting (LUNAUSDT -> Closed) -> SYMBOL_NOT_TRADING."""
    luna = _catalogue("rest/instruments_after.json")["LUNAUSDT"]
    assert luna.status == "closed"
    p = InstrumentPolicy(luna)
    assert V.SYMBOL_NOT_TRADING in {v.code for v in p.validate(luna.min_price, luna.min_order_qty)}
    with pytest.raises(InstrumentFilterError):
        p.enforce(luna.min_price, luna.min_order_qty)


def test_b07_golden_vectors_give_identical_verdicts_over_the_recorded_catalogue() -> None:
    """E08-TC-B07: every golden (price, qty) vector, applied to the recorded BTCUSDT filters with
    the vector's own grid, yields the expected codes and rounded values (single rule source)."""
    doc: dict[str, Any] = json.loads(GOLDEN.read_text(encoding="utf-8"))
    base = _catalogue("rest/instruments_before.json")["BTCUSDT"]
    assert len(doc["cases"]) >= 200
    for case in doc["cases"]:
        raw = case["instrument"]
        inst = base.model_copy(
            update={
                "symbol": raw["symbol"],
                "status": raw["status"],
                "tick_size": Decimal(raw["tick_size"]),
                "qty_step": Decimal(raw["qty_step"]),
                "min_order_qty": Decimal(raw["min_order_qty"]),
                "max_order_qty": Decimal(raw["max_order_qty"]),
                "min_notional": Decimal(raw["min_notional"]),
            }
        )
        p = InstrumentPolicy(inst)
        price, qty = Decimal(case["price"]), Decimal(case["qty"])
        assert p.round_price(price) == Decimal(case["expected_rounded_price"]), case
        assert p.round_qty(qty) == Decimal(case["expected_rounded_qty"]), case
        got = sorted(v.code.value for v in p.validate(price, qty))
        assert got == sorted(case["expected_violation_codes"]), case
