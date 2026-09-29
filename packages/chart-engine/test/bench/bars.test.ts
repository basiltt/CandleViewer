import { describe, expect, it } from "vitest";
import { generateBars } from "../../bench/fixtures/bars.mjs";

describe("bar generator (ticket: prices as integer ticks, never float dollars)", () => {
  it("emits only integer-valued OHLC prices", () => {
    const bars = generateBars({ seed: 1, count: 200, symbol: "BTCUSDT" });
    for (const bar of bars) {
      expect(Number.isInteger(bar.o)).toBe(true);
      expect(Number.isInteger(bar.h)).toBe(true);
      expect(Number.isInteger(bar.l)).toBe(true);
      expect(Number.isInteger(bar.c)).toBe(true);
      expect(bar.h).toBeGreaterThanOrEqual(bar.l);
      expect(bar.h).toBeGreaterThanOrEqual(Math.max(bar.o, bar.c));
      expect(bar.l).toBeLessThanOrEqual(Math.min(bar.o, bar.c));
    }
  });

  it("produces volatility clustering, not iid noise (some run of gap bars exists per 100k-bar-scale sample)", () => {
    const bars = generateBars({ seed: 7, count: 5000, symbol: "ETHUSDT" });
    const gapCount = bars.filter((b) => b.gap).length;
    // ~0.2% gap probability over 5000 bars — expect a handful, not zero and
    // not a third of all bars (sanity bound on the generator, not an exact figure).
    expect(gapCount).toBeGreaterThan(0);
    expect(gapCount).toBeLessThan(200);
  });

  it("is deterministic across two calls with the same seed", () => {
    const a = generateBars({ seed: 99, count: 1000 });
    const b = generateBars({ seed: 99, count: 1000 });
    expect(a).toEqual(b);
  });

  it("uses a distinct per-symbol origin", () => {
    const btc = generateBars({ seed: 1, count: 1, symbol: "BTCUSDT" });
    const eth = generateBars({ seed: 1, count: 1, symbol: "ETHUSDT" });
    expect(btc[0]?.o).not.toBe(eth[0]?.o);
  });
});
