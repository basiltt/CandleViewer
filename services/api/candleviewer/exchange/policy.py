"""`InstrumentPolicy` — one shared rounding/validation rule for price and
quantity (`US-MKT-004`, ticket `E08-S02`).

This is the single source of the rounding algorithm. `packages/protocol`
publishes a *generated* data table (per-symbol steps/limits) plus a tiny
port of this same algorithm for the web client
(`tools/gen/export_instrument_policy_rules.py` writes the data table that
`packages/protocol/scripts/generate-policy-rules.mjs` turns into TS); the
cross-language property test (`tests/unit/exchange/test_policy_property.py`
on the Python side, `packages/protocol/test/policy-equivalence.test.ts` on
the TS side, both consuming the same generated corpus under
`packages/fixtures/golden/policy/`) proves the two never disagree per the
ticket's "Client and server never disagree" scenario.

Design notes (`docs/plan/24-internal-schemas.md` §1.3 rule 1/2, §1.5):

- All arithmetic is `Decimal`; the exponent for each field's `quantize()`
  call is derived from the instrument's own `tick_size`/`qty_step` (never a
  hard-coded exponent), per ticket "Technical notes".
- `round_price(price, mode="nearest")` rounds to the nearest tick using
  `ROUND_HALF_EVEN` (banker's rounding — deterministic, no directional
  bias for a display/blur-snap value; the ticket scopes only the `nearest`
  mode used by the order-ticket blur/snap interaction, C-1.2 out-of-scope
  note: conservative/aggressive execution-side rounding modes belong to
  E29's OMS path, not this Story).
- `round_qty(qty, mode="down")` always floors to `qty_step` — rounding up
  could exceed available margin or a risk cap (§1.3 rule 2). `mode` is
  accepted (not just implied) so a future caller cannot silently change
  this invariant without it being visible at the call site; only `"down"`
  is implemented per ticket scope.
- `Decimal` quanta are never constructed per call: the quantum (e.g.
  `Decimal("0.1")`) is read directly off the instrument's `tick_size`/
  `qty_step` fields and reused, keeping `validate()` allocation the same
  regardless of how many times a symbol is re-validated (Performance
  notes: p99 <=50 us, no per-call `Decimal` context construction).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import Px, Qty

__all__ = [
    "FilterViolation",
    "FilterViolationCode",
    "InstrumentPolicy",
    "PriceRoundMode",
    "QtyRoundMode",
]


class PriceRoundMode(StrEnum):
    """Price rounding modes (§1.3 rule 1). Only `NEAREST` is implemented by
    this Story; `CONSERVATIVE`/`AGGRESSIVE` (execution-side, side-aware
    rounding) are E29/OMS scope and are deliberately not exposed here."""

    NEAREST = "nearest"


class QtyRoundMode(StrEnum):
    """Quantity rounding modes (§1.3 rule 2). `DOWN` (floor) is the only
    mode: rounding a quantity up can exceed available margin or a risk
    cap, so no other mode is ever offered."""

    DOWN = "down"


class FilterViolationCode(StrEnum):
    """Stable violation codes (ticket "Scope / Deliverables"). Each carries
    a plain-language `user_message` naming the limit (accessibility
    notes)."""

    PRICE_NOT_TICK_MULTIPLE = "PRICE_NOT_TICK_MULTIPLE"
    QTY_NOT_LOT_MULTIPLE = "QTY_NOT_LOT_MULTIPLE"
    QTY_BELOW_MIN = "QTY_BELOW_MIN"
    QTY_ABOVE_MAX = "QTY_ABOVE_MAX"
    NOTIONAL_BELOW_MIN = "NOTIONAL_BELOW_MIN"
    SYMBOL_NOT_TRADING = "SYMBOL_NOT_TRADING"


@dataclass(frozen=True)
class FilterViolation:
    """One violated instrument filter. Violations are data, not exceptions
    (Technical notes), so a UI can show several at once; the server-side
    enforcement hook (`InstrumentPolicy.enforce`) is what turns a non-empty
    list into an `InstrumentFilterError` for the order path."""

    code: FilterViolationCode
    user_message: str


class InstrumentPolicy:
    """One rule source for price/qty rounding and filter validation,
    consumed by both the server order path (`enforce`, wired into E29's
    order entry per "Server-side enforcement hook") and the generated
    client rule table (same algorithm, ported; see module docstring).

    Constructed once per `Instrument` and cached (Performance notes: no
    `Decimal` context allocated per call) — callers hold one
    `InstrumentPolicy` per symbol, not one per validation call.
    """

    __slots__ = ("_instrument",)

    def __init__(self, instrument: Instrument) -> None:
        self._instrument = instrument

    @property
    def instrument(self) -> Instrument:
        return self._instrument

    def round_price(self, price: Px, *, mode: PriceRoundMode = PriceRoundMode.NEAREST) -> Px:
        """Round `price` to the nearest `tick_size` multiple (§1.3 rule 1,
        ticket "Tick rounding" scenario: `50000.04` @ `tick_size=0.1` ->
        `50000.0`). `ROUND_HALF_EVEN` is deterministic and has no
        directional bias, appropriate for a display/blur-snap value."""
        tick = self._instrument.tick_size
        if mode is not PriceRoundMode.NEAREST:  # pragma: no cover - exhaustive StrEnum
            raise ValueError(f"unsupported price round mode: {mode!r}")
        steps = (price / tick).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
        return steps * tick

    def round_qty(self, qty: Qty, *, mode: QtyRoundMode = QtyRoundMode.DOWN) -> Qty:
        """Floor `qty` to the nearest `qty_step` multiple (§1.3 rule 2,
        ticket "Lot rounding always rounds down" scenario: `0.0019` @
        `qty_step=0.001` -> `0.001`, never up)."""
        step = self._instrument.qty_step
        if mode is not QtyRoundMode.DOWN:  # pragma: no cover - exhaustive StrEnum
            raise ValueError(f"unsupported qty round mode: {mode!r}")
        steps = (qty / step).to_integral_value(rounding=ROUND_DOWN)
        return steps * step

    def validate(self, price: Px, qty: Qty) -> list[FilterViolation]:
        """Return every violated filter for `(price, qty)` on this
        instrument (ticket "Out of range" and "Rounding never crosses a
        limit" scenarios). Violations are data — a caller may still see
        several at once (e.g. below `min_notional` *and* not a tick
        multiple) so the UI can show them together (Technical notes).

        `price`/`qty` are the values as the caller intends to submit them
        (already rounded, or not — this method does not mutate its
        arguments; it only reports what is wrong with what it was given).
        Callers building an order ticket call `round_price`/`round_qty`
        first and then `validate` the rounded result, per the ticket's
        "rounded value is reported before submission" requirement.
        """
        inst = self._instrument
        violations: list[FilterViolation] = []

        if inst.status != "trading":
            violations.append(
                FilterViolation(
                    code=FilterViolationCode.SYMBOL_NOT_TRADING,
                    user_message=(
                        f"{inst.symbol} is not currently trading (status: {inst.status})."
                    ),
                )
            )

        if (price % inst.tick_size) != 0:
            violations.append(
                FilterViolation(
                    code=FilterViolationCode.PRICE_NOT_TICK_MULTIPLE,
                    user_message=f"Price must be a multiple of {inst.tick_size}.",
                )
            )

        qty_is_lot_multiple = (qty % inst.qty_step) == 0
        if not qty_is_lot_multiple:
            violations.append(
                FilterViolation(
                    code=FilterViolationCode.QTY_NOT_LOT_MULTIPLE,
                    user_message=f"Quantity must be a multiple of {inst.qty_step}.",
                )
            )

        # "Rounding never crosses a limit" scenario: a qty exactly equal to
        # `min_order_qty` that is not a lot multiple must not be silently
        # floored below the minimum before submission. Since `round_qty`
        # always floors, the value that would actually reach the exchange
        # is `floor(qty, qty_step)`, not the raw `qty` — so the minimum
        # check compares against that effective, submittable quantity
        # rather than the raw input.
        effective_qty = qty if qty_is_lot_multiple else self.round_qty(qty)
        if effective_qty < inst.min_order_qty:
            violations.append(
                FilterViolation(
                    code=FilterViolationCode.QTY_BELOW_MIN,
                    user_message=f"Quantity must be at least {inst.min_order_qty}.",
                )
            )
        elif qty > inst.max_order_qty:
            violations.append(
                FilterViolation(
                    code=FilterViolationCode.QTY_ABOVE_MAX,
                    user_message=f"Quantity must not exceed {inst.max_order_qty}.",
                )
            )

        notional = price * qty
        if notional < inst.min_notional:
            violations.append(
                FilterViolation(
                    code=FilterViolationCode.NOTIONAL_BELOW_MIN,
                    user_message=f"Order notional must be at least {inst.min_notional}.",
                )
            )

        return violations

    def enforce(self, price: Px, qty: Qty) -> None:
        """Server-side enforcement hook (Scope / Deliverables: "exposed for
        E29's order path so validation cannot be bypassed by calling the
        API directly"). Raises the first `InstrumentFilterError` for any
        violated filter; callers that want every violation at once use
        `validate` directly (e.g. the API layer building a problem
        response for the UI)."""
        # Imported lazily: `exchange.base` is upstream of `exchange` in the
        # module graph only via this optional convenience wrapper, and the
        # error taxonomy module has no dependency of its own back onto
        # `policy.py`, so this is safe, but keeping the import local avoids
        # widening the module's top-level import surface for callers that
        # only need `validate`.
        from candleviewer.exchange.base.errors import InstrumentFilterError

        violations = self.validate(price, qty)
        if violations:
            first = violations[0]
            raise InstrumentFilterError(
                first.user_message,
                filter_name=first.code.value,
                user_message=first.user_message,
            )
