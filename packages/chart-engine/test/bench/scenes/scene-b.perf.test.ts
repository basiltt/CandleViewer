// Wall-clock budget assertions. Run ONLY by `vitest --project perf` (no coverage):
// V8 coverage instrumentation inflates timings. See docs/plan/26-chart-engine-design.md.
import { describe, expect, it } from "vitest";
import { SceneB } from "../../../bench/scenes/scene-b.mjs";
import { runScenario } from "../../../bench/runner.mjs";
import { captureMachineDescriptor } from "../../../bench/machine.mjs";
import { generateM0Fixture } from "../../../bench/fixtures/index.mjs";

interface Ext {
  textBatchMs: number;
  outlinePassMs: number;
  residualMs?: number;
}

describe("perf budgets: SceneB", () => {
  it("reformat of 2,500 cells stays within a generous multiple of the 4 ms budget", () => {
    const scene = new SceneB();
    scene.init(generateM0Fixture({ seed: 1, barCount: 200 }));
    const ms = Math.min(
      scene.setFormat("compact"),
      scene.setFormat("full"),
      scene.setFormat("compact"),
    );
    expect(ms).toBeLessThan(20);
  });
  it("SDF arm holds B3: p95 <= 16 ms, text <= 2 ms", () => {
    const scene = new SceneB({ arm: "sdf" });
    scene.init(generateM0Fixture({ seed: 1, barCount: 200 }));
    const r = runScenario({
      scene,
      scenario: "B3",
      durationMs: 1000,
      repetitions: 3,
      runtime: "chromium",
      runtimeVersion: "node",
      machine: captureMachineDescriptor({ gpu: "stub", driver: "stub" }),
      seed: 1,
      lodProfile: "LOD_PROFILE_M0",
      peakProcessMemMB: 1,
      peakProcessMemSource: "test",
    });
    const ext = scene.extendedStats() as unknown as Ext;
    expect(r.p95).toBeLessThanOrEqual(16);
    expect(ext.textBatchMs + ext.outlinePassMs).toBeLessThanOrEqual(2.0);
  });
});
