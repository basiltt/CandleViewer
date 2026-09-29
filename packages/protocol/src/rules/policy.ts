// Hand-ported TS mirror of `InstrumentPolicy`
// (services/api/candleviewer/exchange/policy.py) — ticket `E08-S02`,
// "Client and server never disagree" scenario.
//
// This is a deliberate, minimal *port* (not a generated file): the algorithm
// is small enough that porting once and proving equivalence via the shared
// corpus (packages/fixtures/golden/policy/corpus.json, consumed by both
// test/policy-equivalence.test.ts here and
// services/api/tests/unit/exchange/test_policy_corpus_equivalence.py) is
// safer than machine-translating Python into TS. `src/generated/policy/`
// (the literal-union enum types) IS generated, from the same Python source,
// so the two can never silently drift apart on violation-code spelling.
//
// All arithmetic is exact fixed-point on BigInt-scaled integers — never
// `number`/`Math` — mirroring the Python side's `Decimal` usage (no float
// for price/qty/notional, per the ticket's Technical notes).
import type { FilterViolationCode } from "../generated/policy/index.js";

export type { FilterViolationCode } from "../generated/policy/index.js";

/** One violated instrument filter (mirrors `FilterViolation` dataclass). */
export interface FilterViolation {
  readonly code: FilterViolationCode;
  readonly userMessage: string;
}

/** The subset of `Instrument` fields `InstrumentPolicy` reads, as decimal strings
 * (exact — never `number` — matching how the REST/WS layer serialises `Decimal`). */
export interface PolicyInstrument {
  readonly symbol: string;
  readonly status: string; // "trading" | "pre_launch" | "delivering" | "closed"
  readonly tickSize: string;
  readonly qtyStep: string;
  readonly minOrderQty: string;
  readonly maxOrderQty: string;
  readonly minNotional: string;
}

/** Exact decimal value: `unscaled * 10^-scale`. */
interface FixedDecimal {
  readonly unscaled: bigint;
  readonly scale: number;
}

function parseDecimal(input: string): FixedDecimal {
  const trimmed = input.trim();
  const negative = trimmed.startsWith("-");
  const unsigned = negative ? trimmed.slice(1) : trimmed;
  const [intPart, fracPart = ""] = unsigned.split(".");
  const digits = `${intPart}${fracPart}` || "0";
  const unscaled = BigInt(digits) * (negative ? -1n : 1n);
  return { unscaled, scale: fracPart.length };
}

function toDecimalString(value: FixedDecimal): string {
  const negative = value.unscaled < 0n;
  const digits = (negative ? -value.unscaled : value.unscaled).toString();
  if (value.scale === 0) {
    return `${negative ? "-" : ""}${digits}`;
  }
  const padded = digits.padStart(value.scale + 1, "0");
  const intPart = padded.slice(0, padded.length - value.scale);
  const fracPart = padded.slice(padded.length - value.scale);
  return `${negative ? "-" : ""}${intPart}.${fracPart}`;
}

/** Rescales both operands to the larger of the two scales (exact — always a power-of-ten multiply). */
function align(a: FixedDecimal, b: FixedDecimal): [bigint, bigint, number] {
  const scale = Math.max(a.scale, b.scale);
  const aScaled = a.unscaled * 10n ** BigInt(scale - a.scale);
  const bScaled = b.unscaled * 10n ** BigInt(scale - b.scale);
  return [aScaled, bScaled, scale];
}

function compare(a: FixedDecimal, b: FixedDecimal): number {
  const [aScaled, bScaled] = align(a, b);
  if (aScaled < bScaled) return -1;
  if (aScaled > bScaled) return 1;
  return 0;
}

function multiply(a: FixedDecimal, b: FixedDecimal): FixedDecimal {
  return { unscaled: a.unscaled * b.unscaled, scale: a.scale + b.scale };
}

/** Exact modulo (`price % tick_size` in Python `Decimal` semantics: result has the sign of the dividend). */
function mod(a: FixedDecimal, b: FixedDecimal): FixedDecimal {
  const [aScaled, bScaled, scale] = align(a, b);
  return { unscaled: aScaled % bScaled, scale };
}

function isZero(value: FixedDecimal): boolean {
  return value.unscaled === 0n;
}

/**
 * `steps = round(a / b)` using round-half-to-even (banker's rounding),
 * matching `Decimal.quantize(..., rounding=ROUND_HALF_EVEN)`. Returns the
 * integer step count as a bigint; `b` must be non-zero and positive.
 */
function divideRoundHalfEven(a: FixedDecimal, b: FixedDecimal): bigint {
  const [aScaled, bScaled] = align(a, b);
  const quotient = aScaled / bScaled;
  const remainder = aScaled % bScaled;
  if (remainder === 0n) return quotient;
  const twiceRemainder = remainder * 2n;
  const absTwiceRemainder = twiceRemainder < 0n ? -twiceRemainder : twiceRemainder;
  const absBScaled = bScaled < 0n ? -bScaled : bScaled;
  const roundAwayFromZero = () => (aScaled < 0n ? quotient - 1n : quotient + 1n);
  if (absTwiceRemainder > absBScaled) return roundAwayFromZero();
  if (absTwiceRemainder < absBScaled) return quotient;
  // Exactly halfway: round to even.
  return quotient % 2n === 0n ? quotient : roundAwayFromZero();
}

/** `steps = floor(a / b)` (Python's `to_integral_value(rounding=ROUND_DOWN)` — truncation toward zero for positive operands, which is all this domain ever sees). */
function divideFloor(a: FixedDecimal, b: FixedDecimal): bigint {
  const [aScaled, bScaled] = align(a, b);
  const quotient = aScaled / bScaled;
  const remainder = aScaled % bScaled;
  if (remainder !== 0n && aScaled < 0n !== bScaled < 0n) {
    return quotient - 1n;
  }
  return quotient;
}

function stepsToDecimal(steps: bigint, unit: FixedDecimal): FixedDecimal {
  return { unscaled: steps * unit.unscaled, scale: unit.scale };
}

/**
 * Round `price` to the nearest `tickSize` multiple (§1.3 rule 1, ticket
 * "Tick rounding" scenario). Only `mode: "nearest"` exists — same
 * restriction as the Python `PriceRoundMode` enum.
 */
export function roundPrice(price: string, tickSize: string): string {
  const priceDec = parseDecimal(price);
  const tickDec = parseDecimal(tickSize);
  const steps = divideRoundHalfEven(priceDec, tickDec);
  return toDecimalString(stepsToDecimal(steps, tickDec));
}

/**
 * Floor `qty` to the nearest `qtyStep` multiple (§1.3 rule 2, ticket "Lot
 * rounding always rounds down" scenario) — never rounds up.
 */
export function roundQty(qty: string, qtyStep: string): string {
  const qtyDec = parseDecimal(qty);
  const stepDec = parseDecimal(qtyStep);
  const steps = divideFloor(qtyDec, stepDec);
  return toDecimalString(stepsToDecimal(steps, stepDec));
}

/**
 * Returns every violated filter for `(price, qty)` on `instrument`, in the
 * same order as `InstrumentPolicy.validate` (Python side) — a direct port,
 * proven identical via the shared corpus, not re-derived independently.
 */
export function validate(
  price: string,
  qty: string,
  instrument: PolicyInstrument,
): FilterViolation[] {
  const violations: FilterViolation[] = [];
  const priceDec = parseDecimal(price);
  const qtyDec = parseDecimal(qty);
  const tickDec = parseDecimal(instrument.tickSize);
  const stepDec = parseDecimal(instrument.qtyStep);
  const minOrderQtyDec = parseDecimal(instrument.minOrderQty);
  const maxOrderQtyDec = parseDecimal(instrument.maxOrderQty);
  const minNotionalDec = parseDecimal(instrument.minNotional);

  if (instrument.status !== "trading") {
    violations.push({
      code: "SYMBOL_NOT_TRADING",
      userMessage: `${instrument.symbol} is not currently trading (status: ${instrument.status}).`,
    });
  }

  if (!isZero(mod(priceDec, tickDec))) {
    violations.push({
      code: "PRICE_NOT_TICK_MULTIPLE",
      userMessage: `Price must be a multiple of ${instrument.tickSize}.`,
    });
  }

  const qtyIsLotMultiple = isZero(mod(qtyDec, stepDec));
  if (!qtyIsLotMultiple) {
    violations.push({
      code: "QTY_NOT_LOT_MULTIPLE",
      userMessage: `Quantity must be a multiple of ${instrument.qtyStep}.`,
    });
  }

  const effectiveQtyDec = qtyIsLotMultiple
    ? qtyDec
    : parseDecimal(roundQty(qty, instrument.qtyStep));
  if (compare(effectiveQtyDec, minOrderQtyDec) < 0) {
    violations.push({
      code: "QTY_BELOW_MIN",
      userMessage: `Quantity must be at least ${instrument.minOrderQty}.`,
    });
  } else if (compare(qtyDec, maxOrderQtyDec) > 0) {
    violations.push({
      code: "QTY_ABOVE_MAX",
      userMessage: `Quantity must not exceed ${instrument.maxOrderQty}.`,
    });
  }

  const notionalDec = multiply(priceDec, qtyDec);
  if (compare(notionalDec, minNotionalDec) < 0) {
    violations.push({
      code: "NOTIONAL_BELOW_MIN",
      userMessage: `Order notional must be at least ${instrument.minNotional}.`,
    });
  }

  return violations;
}
