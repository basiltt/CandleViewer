import { describe, expect, it } from "vitest";
import { SceneA } from "../../../bench/scenes/scene-a.mjs";
import { runScenario } from "../../../bench/runner.mjs";
import { captureMachineDescriptor } from "../../../bench/machine.mjs";
import { generateM0Fixture } from "../../../bench/fixtures/index.mjs";

function machine() {
  return captureMachineDescriptor({ gpu: "test-stub-gpu", driver: "test-stub-driver" });
}

describe("SceneA (E06-K02 throwaway prototype) — BenchScene conformance + budgets", () => {
  it("processes only the visible window plus prefetch margin, not the full store", () => {
    const fixture = generateM0Fixture({ seed: 1, barCount: 100_000 });
    const scene = new SceneA();
    scene.init(fixture);
    scene.step(0, { tMs: 0, kind: "none" });
    const stats = scene.extendedStats();
    // Default viewport (barSpacing=6, plotWidth=1600) shows ~267 bars; with a
    // 50-bar prefetch margin either side that is well under 1000, nowhere
    // near the 100k total.
    expect(stats.barsTouched).toBeLessThan(1000);
    expect(stats.barsTouched).toBeGreaterThan(0);
    scene.dispose();
  });

  it("static-frame time does not scale measurably with total bar count (10k vs 100k, <=10% diff)", () => {
    const fixture10k = generateM0Fixture({ seed: 1, barCount: 10_000 });
    const fixture100k = generateM0Fixture({ seed: 1, barCount: 100_000 });

    const scene10k = new SceneA();
    scene10k.init(fixture10k);
    scene10k.step(0, { tMs: 0, kind: "none" });
    const t10k = scene10k.stats().frameTimeMs;
    scene10k.dispose();

    const scene100k = new SceneA();
    scene100k.init(fixture100k);
    scene100k.step(0, { tMs: 0, kind: "none" });
    const t100k = scene100k.stats().frameTimeMs;
    scene100k.dispose();

    // Both scenes show the same *visible* window (viewport math is
    // independent of total store length), so frame cost should be
    // near-identical regardless of the 10x difference in total bars.
    const diffRatio = Math.abs(t100k - t10k) / Math.max(t10k, 1e-6);
    expect(diffRatio).toBeLessThanOrEqual(0.1);
  });

  it("exposes currentLod in stats() per US-CHART-001 (aggregation level indicated)", () => {
    const fixture = generateM0Fixture({ seed: 1, barCount: 1000 });
    const scene = new SceneA();
    scene.init(fixture);
    scene.step(0, { tMs: 0, kind: "none" });
    expect(["L0", "L1", "L2"]).toContain(scene.extendedStats().currentLod);
    scene.dispose();
  });

  it("B1: continuous pan holds p95 <= 12ms and drawCalls <= 8", () => {
    const fixture = generateM0Fixture({ seed: 42, barCount: 100_000 });
    const scene = new SceneA();
    scene.init(fixture);
    const report = runScenario({
      scene,
      scenario: "B1",
      durationMs: 5000,
      repetitions: 3,
      runtime: "chromium",
      runtimeVersion: "test",
      machine: machine(),
      seed: 42,
      lodProfile: "LOD_PROFILE_M0",
      peakProcessMemMB: 0,
      peakProcessMemSource: "test",
    });
    scene.dispose();
    expect(report.p95).toBeLessThanOrEqual(12);
    expect(report.drawCalls).toBeLessThanOrEqual(8);
  });

  it("B2: zoom sweep holds p95 <= 14ms with <= 6 LOD changes", () => {
    const fixture = generateM0Fixture({ seed: 42, barCount: 100_000 });
    const scene = new SceneA();
    scene.init(fixture);
    const report = runScenario({
      scene,
      scenario: "B2",
      durationMs: 5000,
      repetitions: 3,
      runtime: "chromium",
      runtimeVersion: "test",
      machine: machine(),
      seed: 42,
      lodProfile: "LOD_PROFILE_M0",
      peakProcessMemMB: 0,
      peakProcessMemSource: "test",
    });
    scene.dispose();
    expect(report.p95).toBeLessThanOrEqual(14);
    // lodChanges is scene-level state, read directly (report doesn't carry it).
  });

  it("B2: LOD level changes over a full 0.1->50 px/bar sweep stay within the hysteresis budget (<=6)", () => {
    const fixture = generateM0Fixture({ seed: 42, barCount: 100_000 });
    const scene = new SceneA();
    scene.init(fixture);
    for (let i = 0; i <= 300; i += 1) {
      const tMs = (i / 300) * 20_000;
      const progress = tMs / 20_000;
      const pxPerBar = 0.1 + progress * (50 - 0.1);
      scene.step(tMs, { tMs, kind: "zoom", payload: { pxPerBar } });
    }
    expect(scene.lodChanges).toBeLessThanOrEqual(6);
    scene.dispose();
  });

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

  it("parks with zero allocation counter when idle (render-on-demand contract)", () => {
    const fixture = generateM0Fixture({ seed: 1, barCount: 1000 });
    const scene = new SceneA();
    scene.init(fixture);
    scene.step(0, { tMs: 0, kind: "none" });
    expect(scene.extendedStats().allocationsInFramePath).toBe(0);
    scene.dispose();
  });
});
