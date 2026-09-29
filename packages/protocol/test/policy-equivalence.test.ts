// Cross-language equivalence proof (ticket `E08-S02`, "Client and server
// never disagree" scenario): the shared, generated corpus consumed by both
// `services/api` and this package must match `src/rules/policy.ts` exactly
// for every case.
//
// See `tools/gen/export_instrument_policy_corpus.py`'s module docstring for
// why the generator itself is stdlib Python (no candleviewer import); this
// test is what proves the TS port doesn't quietly diverge from it (the
// Python-side twin is
// `services/api/tests/unit/exchange/test_policy_corpus_equivalence.py`).
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { roundPrice, roundQty, validate, type PolicyInstrument } from "../src/rules/policy.js";

/**
 * Compares two decimal strings by *value*, not representation — matching
 * Python `Decimal` equality (`Decimal("150") == Decimal("150.000")` is
 * `True`: trailing zeros/exponent never affect equality, only precision of
 * display). The Python-side equivalence test
 * (`test_policy_corpus_equivalence.py`) relies on exactly this, so the TS
 * side must compare the same way rather than demanding identical trailing
 * zeros, which Python's own `Decimal` division does not guarantee either.
 */
function decimalsEqual(a: string, b: string): boolean {
  const parse = (s: string): { unscaled: bigint; scale: number } => {
    const negative = s.startsWith("-");
    const unsigned = negative ? s.slice(1) : s;
    const [intPart, fracPart = ""] = unsigned.split(".");
    const digits = `${intPart}${fracPart}` || "0";
    const unscaled = BigInt(digits) * (negative ? -1n : 1n);
    return { unscaled, scale: fracPart.length };
  };
  const pa = parse(a);
  const pb = parse(b);
  const scale = Math.max(pa.scale, pb.scale);
  const av = pa.unscaled * 10n ** BigInt(scale - pa.scale);
  const bv = pb.unscaled * 10n ** BigInt(scale - pb.scale);
  return av === bv;
}

const __dirname = dirname(fileURLToPath(import.meta.url));
const corpusPath = join(__dirname, "..", "..", "fixtures", "golden", "policy", "corpus.json");

interface CorpusCase {
  instrument: {
    symbol: string;
    status: string;
    tick_size: string;
    qty_step: string;
    min_order_qty: string;
    max_order_qty: string;
    min_notional: string;
  };
  price: string;
  qty: string;
  expected_rounded_price: string;
  expected_rounded_qty: string;
  expected_violation_codes: string[];
}

interface CorpusDocument {
  violation_codes: string[];
  cases: CorpusCase[];
}

function loadCorpus(): CorpusDocument {
  return JSON.parse(readFileSync(corpusPath, "utf8")) as CorpusDocument;
}

function toPolicyInstrument(raw: CorpusCase["instrument"]): PolicyInstrument {
  return {
    symbol: raw.symbol,
    status: raw.status,
    tickSize: raw.tick_size,
    qtyStep: raw.qty_step,
    minOrderQty: raw.min_order_qty,
    maxOrderQty: raw.max_order_qty,
    minNotional: raw.min_notional,
  };
}

describe("policy corpus equivalence", () => {
  it("the corpus file exists and is non-empty", () => {
    const corpus = loadCorpus();
    expect(corpus.cases.length).toBeGreaterThan(0);
  });

  it("agrees with every generated case's rounded price, rounded qty and violation codes", () => {
    const corpus = loadCorpus();
    for (const testCase of corpus.cases) {
      const instrument = toPolicyInstrument(testCase.instrument);

      expect(
        decimalsEqual(
          roundPrice(testCase.price, instrument.tickSize),
          testCase.expected_rounded_price,
        ),
      ).toBe(true);
      expect(
        decimalsEqual(roundQty(testCase.qty, instrument.qtyStep), testCase.expected_rounded_qty),
      ).toBe(true);

      const violations = validate(testCase.price, testCase.qty, instrument);
      expect(violations.map((v) => v.code)).toEqual(testCase.expected_violation_codes);
    }
  });
});
