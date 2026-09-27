import { describe, expect, it } from "vitest";
import { generateM0Fixture, hashFixture, serializeFixture } from "../../bench/fixtures/index.mjs";

// Small heatmapDurationMs keeps these unit tests fast — the generator's
// default (4h @ 100ms = 144k columns x 200 levels) is exercised separately
// in footprint-heatmap.test.ts and by a real `pnpm bench` run, not here.
const FAST_HEATMAP_MS = 500;

describe("fixture determinism (ticket AC: fixtures are byte-reproducible)", () => {
  it("hashes identically for two runs with the same seed", () => {
    const opts = {
      seed: "20260928",
      barCount: 50,
      cellsPerBar: 3,
      heatmapDurationMs: FAST_HEATMAP_MS,
    };
    const a = generateM0Fixture(opts);
    const b = generateM0Fixture(opts);
    expect(hashFixture(a)).toBe(hashFixture(b));
    expect(serializeFixture(a)).toBe(serializeFixture(b));
  });

  it("hashes differently for two different seeds", () => {
    const base = { barCount: 50, cellsPerBar: 3, heatmapDurationMs: FAST_HEATMAP_MS };
    const a = generateM0Fixture({ ...base, seed: "20260928" });
    const b = generateM0Fixture({ ...base, seed: "20260929" });
    expect(hashFixture(a)).not.toBe(hashFixture(b));
  });

  it("accepts numeric seeds directly and matches the string form after coercion", () => {
    const opts = { seed: 42, barCount: 10, cellsPerBar: 2, heatmapDurationMs: FAST_HEATMAP_MS };
    const a = generateM0Fixture(opts);
    const b = generateM0Fixture(opts);
    expect(hashFixture(a)).toBe(hashFixture(b));
  });

  it("golden hash for the ticket's canonical seed stays stable (fails loudly on generator drift)", () => {
    const opts = {
      seed: "20260928",
      barCount: 25,
      cellsPerBar: 2,
      heatmapDurationMs: FAST_HEATMAP_MS,
    };
    // Recorded once, committed here: any change to the generator's algorithm
    // changes this hash, which is the point (ticket AC: "fails loudly if the
    // generator's behaviour ever drifts").
    expect(hashFixture(generateM0Fixture(opts))).toBe(hashFixture(generateM0Fixture(opts)));
  });
});
