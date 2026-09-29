// Synthetic 200-depth heatmap column stream (E06-K01 ticket bullet 3).
// 100ms cadence, covering a 4h trail plus a 30-minute continuation for the
// B10 soak scenario (docs/plan/06-performance-and-load-standard.md §4.2).
import { mulberry32 } from "./rng.mjs";

const CADENCE_MS = 100;
const FOUR_HOURS_MS = 4 * 60 * 60 * 1000;
const THIRTY_MIN_MS = 30 * 60 * 1000;

/**
 * @typedef {{ tMs: number, levels: Int32Array }} HeatmapColumn
 */

/**
 * Generates a heatmap column stream: one column every `CADENCE_MS`, each with
 * `depth` price levels (bid+ask combined, signed: positive = bid size,
 * negative = ask size) covering a 4h trail plus a 30-min soak continuation.
 *
 * @param {{ seed: number, depth?: number, startMs?: number, soak?: boolean, durationMs?: number }} opts
 *   `durationMs` overrides the default 4h(+30m soak) trail — used by tests to
 *   generate a small, fast slice while keeping the same generator logic.
 * @returns {HeatmapColumn[]}
 */
export function generateHeatmapColumns(opts) {
  const { seed, depth = 200, startMs = 0, soak = false, durationMs: durationOverride } = opts;
  const rng = mulberry32(seed);
  const durationMs = durationOverride ?? FOUR_HOURS_MS + (soak ? THIRTY_MIN_MS : 0);
  const columnCount = Math.floor(durationMs / CADENCE_MS);

  const columns = [];
  const levels = new Float64Array(depth);
  for (let i = 0; i < columnCount; i += 1) {
    for (let lvl = 0; lvl < depth; lvl += 1) {
      // Random walk per level, decaying pull toward zero so depth doesn't
      // diverge unbounded over a 4h+ run.
      const decay = levels[lvl] * 0.98;
      const noise = (rng() - 0.5) * 40;
      levels[lvl] = decay + noise;
    }
    columns.push({
      tMs: startMs + i * CADENCE_MS,
      levels: Int32Array.from(levels, (v) => Math.round(v)),
    });
  }
  return columns;
}

export const HEATMAP_CADENCE_MS = CADENCE_MS;
