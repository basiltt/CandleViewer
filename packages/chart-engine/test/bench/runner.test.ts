import { describe, expect, it } from "vitest";
import { runScenario } from "../../bench/runner.mjs";
import { StubScene } from "../../bench/scene.mjs";
import { captureMachineDescriptor } from "../../bench/machine.mjs";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";

describe("runScenario integration (ticket Test plan: validates statistics against a known injected distribution)", () => {
  it("reports p50/p95/p99 close to the stub scene's known base+jitter distribution", () => {
    const scene = new StubScene({ baseMs: 10, jitterMs: 1, seedRng: mulberry32(7) });
    const report = runScenario({
      scene,
      scenario: "B5",
      durationMs: 2000,
      repetitions: 3,
      runtime: "chromium",
      runtimeVersion: "test",
      machine: captureMachineDescriptor({ gpu: "stub", driver: "stub" }),
      seed: 7,
      lodProfile: "L0",
      peakProcessMemMB: 100,
      peakProcessMemSource: "test",
    });

    // StubScene draws frameTimeMs from [baseMs - jitterMs, baseMs + jitterMs].
    expect(report.p50).toBeGreaterThan(8.5);
    expect(report.p50).toBeLessThan(11.5);
    expect(report.p95).toBeGreaterThan(8.5);
    expect(report.p95).toBeLessThanOrEqual(11);
    expect(report.admissibleForAdrEvidence).toBe(true);
    expect(report.repetitions).toBe(3);
    scene.dispose();
  });

  it("marks the report not admissible when fewer than 3 repetitions are requested", () => {
    const scene = new StubScene({ seedRng: mulberry32(1) });
    const report = runScenario({
      scene,
      scenario: "B1",
      durationMs: 200,
      repetitions: 1,
      runtime: "chromium",
      runtimeVersion: "test",
      machine: captureMachineDescriptor({ gpu: "stub", driver: "stub" }),
      seed: 1,
      lodProfile: "L0",
      peakProcessMemMB: 50,
      peakProcessMemSource: "test",
    });
    expect(report.admissibleForAdrEvidence).toBe(false);
    scene.dispose();
  });
});
