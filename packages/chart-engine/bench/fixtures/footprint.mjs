// Synthetic footprint-cell stream generator (E06-K01 ticket bullet 2).
// Density target: enough cells that 2,500 are visible at the L0 threshold
// (E06-D01 owns the exact threshold value; this generator is parameterised
// by `cellsPerBar` so K02/K03 can tune density without touching this file).
import { mulberry32 } from "./rng.mjs";

/**
 * @typedef {{ barIndex: number, priceTicks: number, bid: number, ask: number, tradeCount: number }} FootprintCell
 */

/**
 * Generates a footprint cell stream aligned to a bar series: each bar gets
 * `cellsPerBar` price-level cells with bid/ask volume and trade count.
 *
 * @param {{ seed: number, barCount: number, cellsPerBar?: number, tickSize?: number }} opts
 * @returns {FootprintCell[]}
 */
export function generateFootprintCells(opts) {
  const { seed, barCount, cellsPerBar = 25, tickSize = 1 } = opts;
  const rng = mulberry32(seed);
  const cells = [];
  for (let bar = 0; bar < barCount; bar += 1) {
    const basePriceTicks = Math.round(rng() * 1000) * tickSize;
    for (let level = 0; level < cellsPerBar; level += 1) {
      const bid = Math.round(rng() * 200);
      const ask = Math.round(rng() * 200);
      cells.push({
        barIndex: bar,
        priceTicks: basePriceTicks + level * tickSize,
        bid,
        ask,
        tradeCount: Math.max(0, Math.round((bid + ask) / 8)),
      });
    }
  }
  return cells;
}
