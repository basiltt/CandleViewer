import { describe, expect, it } from "vitest";
import { runBenchScene } from "../bench/harness.js";

describe("bench harness contract", () => {
  it("returns the shape CONSTITUTION.md §9 #16 requires", () => {
    const result = runBenchScene();
    expect(result).toEqual({
      frameTimeMs: { p50: 0, p95: 0, p99: 0 },
      drawCalls: 0,
      memoryMb: 0,
    });
  });
});
