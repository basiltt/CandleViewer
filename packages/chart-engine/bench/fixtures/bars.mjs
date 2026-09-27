// Synthetic OHLCV bar generator (E06-K01 ticket "Fixture generator" bullet 1).
// Prices are emitted as INTEGER TICKS with a per-symbol origin — never float
// dollars (26-chart-engine-design.md §3.3 precision rule). Deterministic:
// same seed -> byte-identical output (ticket AC "Fixtures are byte-reproducible").
import { mulberry32 } from "./rng.mjs";

/** Per-symbol tick-size origin, kept small and explicit (no float math). */
export const SYMBOL_TICK_ORIGIN = {
  BTCUSDT: { originTicks: 6_000_000, tickSize: 1 }, // $60,000.00 @ 0.01 tick
  ETHUSDT: { originTicks: 300_000, tickSize: 1 }, // $3,000.00 @ 0.01 tick
};

/**
 * @typedef {{ tOpenMs: number, o: number, h: number, l: number, c: number, v: number, gap: boolean }} SyntheticBar
 */

/**
 * Generates `count` synthetic 1-minute bars with volatility clustering
 * (GARCH-like: a run of large moves is followed by more large moves) and
 * occasional session gaps (a bar's open jumps away from the prior close).
 *
 * @param {{ seed: number, count?: number, symbol?: keyof typeof SYMBOL_TICK_ORIGIN, startMs?: number }} opts
 * @returns {SyntheticBar[]}
 */
export function generateBars(opts) {
  const {
    seed,
    count = 100_000,
    symbol = "BTCUSDT",
    startMs = Date.UTC(2026, 0, 1, 0, 0, 0),
  } = opts;
  const rng = mulberry32(seed);
  const { originTicks, tickSize } = SYMBOL_TICK_ORIGIN[symbol] ?? SYMBOL_TICK_ORIGIN.BTCUSDT;

  const bars = [];
  let priceTicks = originTicks;
  // Volatility clustering: a slowly-evolving "regime" multiplier on step size.
  let volRegime = 1;

  for (let i = 0; i < count; i += 1) {
    // Regime walk: nudged each bar, clamped to [0.3, 4] so it stays bounded
    // but still produces multi-bar clusters of high/low volatility.
    volRegime += (rng() - 0.5) * 0.08;
    if (volRegime < 0.3) volRegime = 0.3;
    if (volRegime > 4) volRegime = 4;

    const gap = i > 0 && rng() < 0.002; // ~0.2% of bars open with a session gap
    if (gap) {
      const gapTicks = Math.round((rng() - 0.5) * 400 * volRegime);
      priceTicks += gapTicks;
    }

    const open = priceTicks;
    const stepCount = 4; // 4 intra-bar micro-steps to derive high/low/close
    let hi = open;
    let lo = open;
    let cur = open;
    for (let s = 0; s < stepCount; s += 1) {
      const step = Math.round((rng() - 0.5) * 60 * volRegime);
      cur += step;
      if (cur > hi) hi = cur;
      if (cur < lo) lo = cur;
    }
    const close = cur;
    const volume = Math.max(1, Math.round(rng() * 5000 * volRegime));

    bars.push({
      tOpenMs: startMs + i * 60_000,
      o: open,
      h: hi,
      l: lo,
      c: close,
      v: volume,
      gap,
    });
    priceTicks = close;
  }

  return bars.map((b) => ({
    ...b,
    o: b.o * tickSize,
    h: b.h * tickSize,
    l: b.l * tickSize,
    c: b.c * tickSize,
  }));
}
