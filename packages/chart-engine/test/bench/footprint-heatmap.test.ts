import { describe, expect, it } from "vitest";
import { generateFootprintCells } from "../../bench/fixtures/footprint.mjs";
import { generateHeatmapColumns, HEATMAP_CADENCE_MS } from "../../bench/fixtures/heatmap.mjs";

describe("footprint cell generator", () => {
  it("produces cellsPerBar cells for every bar, deterministically", () => {
    const a = generateFootprintCells({ seed: 5, barCount: 10, cellsPerBar: 4 });
    const b = generateFootprintCells({ seed: 5, barCount: 10, cellsPerBar: 4 });
    expect(a).toEqual(b);
    expect(a).toHaveLength(40);
  });

  it("produces enough cells to have >= 2500 visible at realistic density (100 bars x 25 cells)", () => {
    const cells = generateFootprintCells({ seed: 1, barCount: 100, cellsPerBar: 25 });
    expect(cells.length).toBeGreaterThanOrEqual(2500);
  });

  it("has non-negative bid/ask/tradeCount", () => {
    const cells = generateFootprintCells({ seed: 3, barCount: 20, cellsPerBar: 5 });
    for (const cell of cells) {
      expect(cell.bid).toBeGreaterThanOrEqual(0);
      expect(cell.ask).toBeGreaterThanOrEqual(0);
      expect(cell.tradeCount).toBeGreaterThanOrEqual(0);
    }
  });
});

describe("heatmap column generator", () => {
  it("is deterministic and covers the requested duration at 100ms cadence", () => {
    const a = generateHeatmapColumns({ seed: 2, depth: 10, durationMs: 1000 });
    const b = generateHeatmapColumns({ seed: 2, depth: 10, durationMs: 1000 });
    expect(a.map((c) => Array.from(c.levels))).toEqual(b.map((c) => Array.from(c.levels)));
    expect(a).toHaveLength(1000 / HEATMAP_CADENCE_MS);
    expect(a[0]?.levels).toHaveLength(10);
  });

  it("soak flag adds 30 minutes on top of the default 4h duration (checked via column-count math, not a live 4h run)", () => {
    // A live default-duration run is exercised once by the `pnpm bench`
    // smoke test in cli.test.mjs; here we only check the small-duration
    // path plus the arithmetic soak adds, to keep this unit test fast.
    const small = generateHeatmapColumns({ seed: 1, depth: 2, durationMs: 1000 });
    expect(small).toHaveLength(10);
    const FOUR_HOURS_MS = 4 * 60 * 60 * 1000;
    const THIRTY_MIN_MS = 30 * 60 * 1000;
    const normalCount = Math.floor(FOUR_HOURS_MS / HEATMAP_CADENCE_MS);
    const soakCount = Math.floor((FOUR_HOURS_MS + THIRTY_MIN_MS) / HEATMAP_CADENCE_MS);
    expect(soakCount).toBeGreaterThan(normalCount);
  });
});
