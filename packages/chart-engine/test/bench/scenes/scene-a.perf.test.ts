// Wall-clock budget assertion. Run ONLY by `vitest --project perf` (no coverage).
import { describe, expect, it } from "vitest";
import { SceneA } from "../../../bench/scenes/scene-a.mjs";
import { generateM0Fixture } from "../../../bench/fixtures/index.mjs";

describe("perf budgets: SceneA", () => {
  it("B9: cold init to first frame stays under 900ms", () => {
    const fixture = generateM0Fixture({ seed: 42, barCount: 100_000 });
    const start = performance.now();
    const scene = new SceneA();
    scene.init(fixture);
    scene.step(0, { tMs: 0, kind: "none" });
    const elapsed = performance.now() - start;
    expect(elapsed).toBeLessThanOrEqual(900);
    scene.dispose();
  });
});
