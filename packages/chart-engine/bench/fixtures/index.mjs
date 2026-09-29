// Top-level M0 fixture assembly (E06-K01). Combines bars + footprint cells +
// heatmap columns into one deterministic, hashable fixture object.
import { generateBars } from "./bars.mjs";
import { generateFootprintCells } from "./footprint.mjs";
import { generateHeatmapColumns } from "./heatmap.mjs";
import { fnv1aHex, toSeed32 } from "./rng.mjs";

/**
 * @typedef {{
 *   seed: number,
 *   symbol: string,
 *   bars: import("./bars.mjs").SyntheticBar[],
 *   footprintCells: import("./footprint.mjs").FootprintCell[],
 *   heatmapColumns: import("./heatmap.mjs").HeatmapColumn[],
 * }} M0Fixture
 */

/**
 * Generates the full M0 benchmark fixture from a single seed. Same seed ->
 * byte-identical output on any machine (ticket AC1); this is enforced by
 * hashing a canonical JSON-serialisable projection via {@link hashFixture}.
 *
 * @param {{ seed: string|number, symbol?: string, barCount?: number, cellsPerBar?: number, soak?: boolean, heatmapDurationMs?: number }} opts
 * @returns {M0Fixture}
 */
export function generateM0Fixture(opts) {
  const seed32 = typeof opts.seed === "number" ? opts.seed >>> 0 : toSeed32(opts.seed);
  const symbol = opts.symbol ?? "BTCUSDT";
  const barCount = opts.barCount ?? 100_000;
  const cellsPerBar = opts.cellsPerBar ?? 25;

  const bars = generateBars({ seed: seed32, count: barCount, symbol });
  const footprintCells = generateFootprintCells({
    seed: seed32 ^ 0x9e3779b9,
    barCount,
    cellsPerBar,
  });
  const heatmapColumns = generateHeatmapColumns({
    seed: seed32 ^ 0x85ebca6b,
    soak: opts.soak ?? false,
    durationMs: opts.heatmapDurationMs,
  });

  return { seed: seed32, symbol, bars, footprintCells, heatmapColumns };
}

/**
 * Produces a stable, order-preserving JSON string for a fixture, converting
 * typed arrays (which JSON.stringify handles as objects, not arrays) to
 * plain arrays first so the string is portable across Node versions.
 * @param {M0Fixture} fixture
 */
export function serializeFixture(fixture) {
  return JSON.stringify({
    seed: fixture.seed,
    symbol: fixture.symbol,
    bars: fixture.bars,
    footprintCells: fixture.footprintCells,
    heatmapColumns: fixture.heatmapColumns.map((col) => ({
      tMs: col.tMs,
      levels: Array.from(col.levels),
    })),
  });
}

/**
 * Hashes a fixture's canonical serialisation with FNV-1a. Two fixtures
 * generated from the same seed (on any machine, any Node 20.x build) must
 * produce the same hash — this is the ticket's determinism gate.
 * @param {M0Fixture} fixture
 */
export function hashFixture(fixture) {
  return fnv1aHex(serializeFixture(fixture));
}

/**
 * Asserts a fixture's hash matches an expected, previously-recorded hash.
 * (E06-Q01 negative-guard AC: "a run whose fixture hash differs from the
 * recorded seed must fail loudly rather than proceed" — a run that silently
 * regenerates a different fixture than the one it claims to use would
 * invalidate every downstream comparison without any visible symptom.)
 * @param {M0Fixture} fixture
 * @param {string} expectedHash
 */
export function assertFixtureHash(fixture, expectedHash) {
  const actual = hashFixture(fixture);
  if (actual !== expectedHash) {
    throw new Error(
      `[bench] fixture hash mismatch: expected ${expectedHash}, got ${actual} ` +
        `(seed=${fixture.seed}) — refusing to run against an unverified fixture`,
    );
  }
}
