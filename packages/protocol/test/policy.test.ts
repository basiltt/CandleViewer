// Unit tests for the hand-ported `src/rules/policy.ts` (ticket `E08-S02`),
// mirroring the Gherkin scenarios in the ticket body 1:1 with the Python
// suite (`services/api/tests/unit/exchange/test_policy.py`).
import { describe, expect, it } from "vitest";
import { roundPrice, roundQty, validate, type PolicyInstrument } from "../src/rules/policy.js";

const instrument: PolicyInstrument = {
  symbol: "BTCUSDT",
  status: "trading",
  tickSize: "0.1",
  qtyStep: "0.001",
  minOrderQty: "0.001",
  maxOrderQty: "100",
  minNotional: "5",
};

describe("roundPrice", () => {
  it("rounds to the nearest tick multiple (Tick rounding scenario)", () => {
    expect(roundPrice("50000.04", "0.1")).toBe("50000.0");
  });

  it("round-half-to-even on an exact tie", () => {
    // 50000.05 is exactly halfway between 50000.0 and 50000.1; 500000 steps
    // is even, so ROUND_HALF_EVEN keeps it — no directional bias.
    expect(roundPrice("50000.05", "0.1")).toBe("50000.0");
  });
});

describe("roundQty", () => {
  it("always floors to the lot step, never rounds up (Lot rounding scenario)", () => {
    expect(roundQty("0.0019", "0.001")).toBe("0.001");
  });

  it("leaves an exact multiple unchanged", () => {
    expect(roundQty("0.005", "0.001")).toBe("0.005");
  });
});

describe("validate", () => {
  it("reports QTY_ABOVE_MAX for an out-of-range qty (Out of range scenario)", () => {
    const violations = validate("50000.0", "150", instrument);
    expect(violations.map((v) => v.code)).toContain("QTY_ABOVE_MAX");
    const violation = violations.find((v) => v.code === "QTY_ABOVE_MAX");
    expect(violation?.userMessage).toContain("100");
  });

  it("reports QTY_BELOW_MIN for a qty at min_order_qty that is not a lot multiple (Rounding never crosses a limit)", () => {
    const awkward: PolicyInstrument = {
      ...instrument,
      qtyStep: "0.003",
      minOrderQty: "0.001",
    };
    const violations = validate("50000.0", "0.001", awkward);
    expect(violations.map((v) => v.code)).toContain("QTY_BELOW_MIN");
  });

  it("reports SYMBOL_NOT_TRADING for a non-trading instrument", () => {
    const closed: PolicyInstrument = { ...instrument, status: "closed" };
    const violations = validate("50000.0", "1.000", closed);
    expect(violations.map((v) => v.code)).toContain("SYMBOL_NOT_TRADING");
  });

  it("reports NOTIONAL_BELOW_MIN for a too-small order", () => {
    const violations = validate("1.0", "0.001", instrument);
    expect(violations.map((v) => v.code)).toContain("NOTIONAL_BELOW_MIN");
  });

  it("returns no violations for a valid order", () => {
    expect(validate("50000.0", "1.000", instrument)).toEqual([]);
  });

  it("reports several violations together", () => {
    const strict: PolicyInstrument = { ...instrument, status: "closed", minNotional: "100000000" };
    const violations = validate("50000.04", "150", strict);
    const codes = violations.map((v) => v.code);
    expect(codes).toContain("SYMBOL_NOT_TRADING");
    expect(codes).toContain("PRICE_NOT_TICK_MULTIPLE");
    expect(codes).toContain("QTY_ABOVE_MAX");
    expect(codes).toContain("NOTIONAL_BELOW_MIN");
  });
});
