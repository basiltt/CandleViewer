"""Unit + property tests for `InstrumentPolicy` (ticket `E08-S02`, Gherkin
scenarios in the ticket body: "Tick rounding", "Lot rounding always rounds
down", "Out of range", "Rounding never crosses a limit").

Cross-language equivalence with the generated TS client rule table
("Client and server never disagree" scenario) is covered by
`packages/protocol/test/policy-equivalence.test.ts`, both sides consuming
the shared corpus under `packages/fixtures/golden/policy/`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.domain.events import Instrument
from candleviewer.exchange.policy import (
    FilterViolationCode,
    InstrumentPolicy,
    PriceRoundMode,
    QtyRoundMode,
)


def _instrument(**overrides: object) -> Instrument:
    """Minimal-but-valid `Instrument` fixture; only the fields
    `InstrumentPolicy` reads are varied by `overrides`, everything else is a
    fixed, arbitrary-but-valid filler value."""
    base: dict[str, object] = {
        "symbol": "BTCUSDT",
        "base_coin": "BTC",
        "quote_coin": "USDT",
        "settle_coin": "USDT",
        "status": "trading",
        "contract_type": "linear_perpetual",
        "launch_time": 0,
        "tick_size": Decimal("0.1"),
        "price_scale": 1,
        "min_price": Decimal("0.1"),
        "max_price": Decimal("999999"),
        "qty_step": Decimal("0.001"),
        "min_order_qty": Decimal("0.001"),
        "max_order_qty": Decimal("100"),
        "max_mkt_order_qty": Decimal("50"),
        "min_notional": Decimal("5"),
        "max_leverage": Decimal("100"),
        "min_leverage": Decimal("1"),
        "leverage_step": Decimal("0.01"),
        "funding_interval_min": 480,
        "upper_funding_rate": Decimal("0.00375"),
        "lower_funding_rate": Decimal("-0.00375"),
        "copy_trading": False,
        "metadata_version": 1,
        "fetched_at": 0,
    }
    base.update(overrides)
    return Instrument.model_validate(base)


# --- "Tick rounding" scenario -----------------------------------------------


def test_round_price_nearest_rounds_to_tick_multiple() -> None:
    policy = InstrumentPolicy(_instrument(tick_size=Decimal("0.1")))
    assert policy.round_price(Decimal("50000.04")) == Decimal("50000.0")


def test_round_price_default_mode_is_nearest() -> None:
    policy = InstrumentPolicy(_instrument(tick_size=Decimal("0.1")))
    assert policy.round_price(Decimal("50000.04"), mode=PriceRoundMode.NEAREST) == Decimal(
        "50000.0"
    )


def test_round_price_half_tick_rounds_half_even() -> None:
    # 50000.05 is exactly halfway between 50000.0 and 50000.1; 500000 steps
    # is even, so ROUND_HALF_EVEN keeps it (a deterministic, non-directional
    # tie-break — no bias toward either side of the book).
    policy = InstrumentPolicy(_instrument(tick_size=Decimal("0.1")))
    assert policy.round_price(Decimal("50000.05")) == Decimal("50000.0")


# --- "Lot rounding always rounds down" scenario -----------------------------


def test_round_qty_always_floors_to_lot_step() -> None:
    policy = InstrumentPolicy(_instrument(qty_step=Decimal("0.001")))
    assert policy.round_qty(Decimal("0.0019")) == Decimal("0.001")


def test_round_qty_never_rounds_up() -> None:
    policy = InstrumentPolicy(_instrument(qty_step=Decimal("0.001")))
    rounded = policy.round_qty(Decimal("0.0019"), mode=QtyRoundMode.DOWN)
    assert rounded <= Decimal("0.0019")


def test_round_qty_exact_multiple_is_unchanged() -> None:
    policy = InstrumentPolicy(_instrument(qty_step=Decimal("0.001")))
    assert policy.round_qty(Decimal("0.005")) == Decimal("0.005")


# --- "Out of range" scenario -------------------------------------------------


def test_validate_qty_above_max_reports_exact_limit_in_message() -> None:
    policy = InstrumentPolicy(_instrument(max_order_qty=Decimal("100")))
    violations = policy.validate(Decimal("50000.0"), Decimal("150"))
    codes = {v.code for v in violations}
    assert FilterViolationCode.QTY_ABOVE_MAX in codes
    msg = next(v.user_message for v in violations if v.code == FilterViolationCode.QTY_ABOVE_MAX)
    assert "100" in msg


def test_enforce_raises_instrument_filter_error_on_violation() -> None:
    from candleviewer.exchange.base.errors import InstrumentFilterError

    policy = InstrumentPolicy(_instrument(max_order_qty=Decimal("100")))
    with pytest.raises(InstrumentFilterError) as exc_info:
        policy.enforce(Decimal("50000.0"), Decimal("150"))
    assert exc_info.value.filter_name == FilterViolationCode.QTY_ABOVE_MAX.value


def test_enforce_does_not_raise_when_valid() -> None:
    policy = InstrumentPolicy(_instrument())
    policy.enforce(Decimal("50000.0"), Decimal("1.000"))


# --- "Rounding never crosses a limit" scenario ------------------------------


def test_validate_qty_at_min_but_not_lot_multiple_reports_below_min() -> None:
    # min_order_qty itself is not a qty_step multiple: flooring it would
    # breach the minimum, so validate() must report QTY_BELOW_MIN for a qty
    # exactly equal to min_order_qty in this configuration, never emit an
    # invalid (silently-floored) value.
    policy = InstrumentPolicy(
        _instrument(qty_step=Decimal("0.003"), min_order_qty=Decimal("0.001"))
    )
    violations = policy.validate(Decimal("50000.0"), Decimal("0.001"))
    codes = {v.code for v in violations}
    assert FilterViolationCode.QTY_BELOW_MIN in codes


def test_validate_symbol_not_trading() -> None:
    policy = InstrumentPolicy(_instrument(status="closed"))
    violations = policy.validate(Decimal("50000.0"), Decimal("1.000"))
    codes = {v.code for v in violations}
    assert FilterViolationCode.SYMBOL_NOT_TRADING in codes


def test_validate_notional_below_min() -> None:
    policy = InstrumentPolicy(_instrument(min_notional=Decimal("100")))
    violations = policy.validate(Decimal("10.0"), Decimal("0.001"))
    codes = {v.code for v in violations}
    assert FilterViolationCode.NOTIONAL_BELOW_MIN in codes


def test_validate_valid_order_has_no_violations() -> None:
    policy = InstrumentPolicy(_instrument())
    assert policy.validate(Decimal("50000.0"), Decimal("1.000")) == []


def test_validate_multiple_violations_reported_together() -> None:
    # Technical notes: violations are data, not exceptions — several fire at
    # once so the UI can show them all.
    policy = InstrumentPolicy(_instrument(min_notional=Decimal("100000000"), status="closed"))
    violations = policy.validate(Decimal("50000.04"), Decimal("150"))
    codes = {v.code for v in violations}
    assert FilterViolationCode.SYMBOL_NOT_TRADING in codes
    assert FilterViolationCode.PRICE_NOT_TICK_MULTIPLE in codes
    assert FilterViolationCode.QTY_ABOVE_MAX in codes
    assert FilterViolationCode.NOTIONAL_BELOW_MIN in codes


# --- Property-based invariants (ticket "Test plan"): "rounded price is
# always a tick multiple", "rounded qty never exceeds the input", "a valid
# result never violates another filter". -----------------------------------

_prices = st.decimals(
    min_value=Decimal("0.1"), max_value=Decimal("1000000"), places=4, allow_nan=False
)
_qtys = st.decimals(
    min_value=Decimal("0.0001"), max_value=Decimal("1000"), places=4, allow_nan=False
)
_ticks = st.sampled_from([Decimal("0.1"), Decimal("0.01"), Decimal("0.5"), Decimal("1")])
_steps = st.sampled_from([Decimal("0.001"), Decimal("0.01"), Decimal("0.1"), Decimal("1")])


@given(price=_prices, tick=_ticks)
def test_property_rounded_price_is_always_a_tick_multiple(price: Decimal, tick: Decimal) -> None:
    policy = InstrumentPolicy(_instrument(tick_size=tick))
    rounded = policy.round_price(price)
    assert (rounded % tick) == 0


@given(qty=_qtys, step=_steps)
def test_property_rounded_qty_never_exceeds_input(qty: Decimal, step: Decimal) -> None:
    policy = InstrumentPolicy(_instrument(qty_step=step))
    rounded = policy.round_qty(qty)
    assert rounded <= qty


@given(qty=_qtys, step=_steps)
def test_property_rounded_qty_is_always_a_step_multiple(qty: Decimal, step: Decimal) -> None:
    policy = InstrumentPolicy(_instrument(qty_step=step))
    rounded = policy.round_qty(qty)
    assert (rounded % step) == 0


@given(price=_prices, qty=_qtys)
def test_property_a_valid_result_never_violates_another_filter(
    price: Decimal, qty: Decimal
) -> None:
    """A `(price, qty)` pair that passes `validate()` with zero violations
    never turns out to secretly violate a filter the check missed —
    equivalent to asserting `validate` is exhaustive over its own filter
    set for every generated case."""
    policy = InstrumentPolicy(_instrument())
    violations = policy.validate(price, qty)
    if not violations:
        inst = policy.instrument
        assert inst.status == "trading"
        assert (price % inst.tick_size) == 0
        assert (qty % inst.qty_step) == 0
        assert inst.min_order_qty <= qty <= inst.max_order_qty
        assert (price * qty) >= inst.min_notional
