import { describe, expect, it } from "vitest";
import { generateM0Fixture, hashFixture, assertFixtureHash } from "../../bench/fixtures/index.mjs";
import { isAdmissible } from "../../bench/stats.mjs";
import { captureMachineDescriptor, assertDescriptorComplete } from "../../bench/machine.mjs";
import { buildReport } from "../../bench/report.mjs";
import { FRAME_STAGES } from "../../bench/instrumentation.mjs";

// E06-Q01 negative-guard AC: "a run with 2 repetitions must be marked
// inadmissible; a run missing the GPU/driver/OS descriptor must fail; a run
// whose fixture hash differs from the recorded seed must fail loudly rather
// than proceed." None of the three may silently produce a normal-looking
// report — each case below asserts the guard fires, not just that the
// underlying helper returns a value.

describe("negative guard: repetitions < 3", () => {
  it("marks a 2-repetition run as not admissible for ADR evidence", () => {
    expect(isAdmissible(2)).toBe(false);
  });
});

describe("negative guard: missing GPU/driver descriptor", () => {
  it("fails outright (throws) rather than reporting anonymous numbers", () => {
    const incomplete = captureMachineDescriptor(); // gpu/driver left as "unknown-*"
    expect(() => assertDescriptorComplete(incomplete)).toThrowError(/gpu, driver/);
  });

  it("buildReport itself refuses to build a report with an incomplete descriptor", () => {
    const perStage = Object.fromEntries(FRAME_STAGES.map((s) => [s, 1]));
    expect(() =>
      buildReport({
        scenario: "B1",
        runtime: "chromium",
        runtimeVersion: "test",
        machine: captureMachineDescriptor(),
        seed: 1,
        lodProfile: "L0",
        repetitions: 3,
        percentiles: { p50: 9, p95: 9, p99: 9 },
        frameTimeMsOverall: 9,
        perStageMs: perStage,
        drawCalls: 1,
        uploadedBytesPerSec: 1,
        textureMemMB: 1,
        peakProcessMemMB: 1,
        peakProcessMemSource: "test",
      }),
    ).toThrowError(/machine descriptor incomplete/);
  });
});

describe("negative guard: mismatched fixture hash", () => {
  it("fails loudly when the fixture's actual hash differs from the recorded/expected hash", () => {
    const fixture = generateM0Fixture({
      seed: 1,
      barCount: 10,
      cellsPerBar: 1,
      heatmapDurationMs: 200,
    });
    expect(() => assertFixtureHash(fixture, "deadbeef")).toThrowError(/fixture hash mismatch/);
  });

  it("does not throw when the expected hash matches the actual hash", () => {
    const fixture = generateM0Fixture({
      seed: 1,
      barCount: 10,
      cellsPerBar: 1,
      heatmapDurationMs: 200,
    });
    expect(() => assertFixtureHash(fixture, hashFixture(fixture))).not.toThrow();
  });
});
