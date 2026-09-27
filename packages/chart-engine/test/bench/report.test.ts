import { describe, expect, it } from "vitest";
import { buildReport, renderMarkdownSummary, PINNED_CHROMIUM_FLAGS } from "../../bench/report.mjs";
import { captureMachineDescriptor } from "../../bench/machine.mjs";
import { FRAME_STAGES } from "../../bench/instrumentation.mjs";

function perStageMs(totalMs: number) {
  const each = totalMs / FRAME_STAGES.length;
  return Object.fromEntries(FRAME_STAGES.map((s) => [s, each]));
}

describe("buildReport (ticket schema + stage-attribution AC)", () => {
  const machine = captureMachineDescriptor({ gpu: "stub-gpu", driver: "stub-driver" });

  it("builds the full report shape with every named field present", () => {
    const report = buildReport({
      scenario: "B5",
      runtime: "chromium",
      runtimeVersion: "131.0",
      machine,
      seed: 123,
      lodProfile: "L0",
      repetitions: 3,
      percentiles: { p50: 8, p95: 10, p99: 12 },
      frameTimeMsOverall: 9,
      perStageMs: perStageMs(9),
      drawCalls: 42,
      uploadedBytesPerSec: 2048,
      textureMemMB: 16,
      peakProcessMemMB: 256,
      peakProcessMemSource: "process.memoryUsage().rss",
    });
    expect(report.scenario).toBe("B5");
    expect(report.admissibleForAdrEvidence).toBe(true);
    expect(report.gpuFlags).toEqual(PINNED_CHROMIUM_FLAGS);
    expect(Object.keys(report.perStageMs)).toHaveLength(FRAME_STAGES.length);
  });

  it("marks a run with < 3 repetitions as not admissible for ADR evidence", () => {
    const report = buildReport({
      scenario: "B5",
      runtime: "chromium",
      runtimeVersion: "131.0",
      machine,
      seed: 1,
      lodProfile: "L0",
      repetitions: 1,
      percentiles: { p50: 8, p95: 10, p99: 12 },
      frameTimeMsOverall: 9,
      perStageMs: perStageMs(9),
      drawCalls: 1,
      uploadedBytesPerSec: 1,
      textureMemMB: 1,
      peakProcessMemMB: 1,
      peakProcessMemSource: "test",
    });
    expect(report.admissibleForAdrEvidence).toBe(false);
  });

  it("throws when stage costs sum to more than 10% away from the measured frame time", () => {
    expect(() =>
      buildReport({
        scenario: "B5",
        runtime: "chromium",
        runtimeVersion: "131.0",
        machine,
        seed: 1,
        lodProfile: "L0",
        repetitions: 3,
        percentiles: { p50: 8, p95: 10, p99: 12 },
        frameTimeMsOverall: 100,
        perStageMs: perStageMs(1), // stage sum ~1ms vs 100ms measured -> huge residual
        drawCalls: 1,
        uploadedBytesPerSec: 1,
        textureMemMB: 1,
        peakProcessMemMB: 1,
        peakProcessMemSource: "test",
      }),
    ).toThrowError(/unattributed residual/);
  });

  it("throws when the machine descriptor is incomplete", () => {
    expect(() =>
      buildReport({
        scenario: "B5",
        runtime: "chromium",
        runtimeVersion: "131.0",
        machine: captureMachineDescriptor(), // gpu/driver left as "unknown-*"
        seed: 1,
        lodProfile: "L0",
        repetitions: 3,
        percentiles: { p50: 8, p95: 10, p99: 12 },
        frameTimeMsOverall: 9,
        perStageMs: perStageMs(9),
        drawCalls: 1,
        uploadedBytesPerSec: 1,
        textureMemMB: 1,
        peakProcessMemMB: 1,
        peakProcessMemSource: "test",
      }),
    ).toThrowError(/machine descriptor incomplete/);
  });

  it("renders a markdown summary containing the admissibility warning when reps < 3", () => {
    const report = buildReport({
      scenario: "B5",
      runtime: "chromium",
      runtimeVersion: "131.0",
      machine,
      seed: 1,
      lodProfile: "L0",
      repetitions: 1,
      percentiles: { p50: 8, p95: 10, p99: 12 },
      frameTimeMsOverall: 9,
      perStageMs: perStageMs(9),
      drawCalls: 1,
      uploadedBytesPerSec: 1,
      textureMemMB: 1,
      peakProcessMemMB: 1,
      peakProcessMemSource: "test",
    });
    const markdown = renderMarkdownSummary(report);
    expect(markdown).toContain("NOT admissible for ADR evidence");
    expect(markdown).toContain("Per-stage attribution");
  });
});
