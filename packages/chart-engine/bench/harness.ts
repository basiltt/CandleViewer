// Bench harness contract (E02-T03 scaffold; real scenes wired in E06/E11).
// Emits the shape CONSTITUTION.md §9 #16 / E03's engine-bench gate consumes:
// frameTimeMs p50/p95/p99, drawCalls, memoryMb. Values are zero on this empty
// scene — the harness shape must exist now so E06 doesn't invent it later.

export interface BenchResult {
  frameTimeMs: { p50: number; p95: number; p99: number };
  drawCalls: number;
  memoryMb: number;
}

/**
 * Runs the (currently empty) reference scene and returns a deterministic
 * result. No GPU, no DOM, no timers with real-world variance — this is a
 * scaffold, not yet a measurement.
 */
export function runBenchScene(): BenchResult {
  return {
    frameTimeMs: { p50: 0, p95: 0, p99: 0 },
    drawCalls: 0,
    memoryMb: 0,
  };
}
