import { describe, expect, it } from "vitest";
import { FrameInstrumentation, FRAME_STAGES } from "../../bench/instrumentation.mjs";

function fakePerformance() {
  let t = 0;
  const marks: string[] = [];
  const measures: Array<{ name: string; start: string; end: string }> = [];
  return {
    now: () => t,
    mark: (name: string) => marks.push(name),
    measure: (name: string, start: string, end: string) => measures.push({ name, start, end }),
    advance(ms: number) {
      t += ms;
    },
    marks,
    measures,
  };
}

describe("FrameInstrumentation (§7.2 structured spans)", () => {
  it("times a stage and accumulates the mean over frames", () => {
    const perf = fakePerformance();
    const instr = new FrameInstrumentation({ performance: perf });
    instr.timeStage("candleGeometry", () => {
      perf.advance(4);
    });
    instr.endFrame();
    instr.timeStage("candleGeometry", () => {
      perf.advance(2);
    });
    instr.endFrame();
    expect(instr.perStageMeans()["candleGeometry"]).toBeCloseTo(3, 5);
  });

  it("emits mark/measure calls for every stage boundary when enabled", () => {
    const perf = fakePerformance();
    const instr = new FrameInstrumentation({ performance: perf });
    for (const stage of FRAME_STAGES) {
      instr.timeStage(stage, () => {});
    }
    expect(perf.marks).toHaveLength(FRAME_STAGES.length * 2);
    expect(perf.measures).toHaveLength(FRAME_STAGES.length);
  });

  it("skips mark/measure when disabled (perturbation-check AC: disabled path is cheaper)", () => {
    const perf = fakePerformance();
    const instr = new FrameInstrumentation({ performance: perf, enabled: false });
    instr.timeStage("inputHandling", () => perf.advance(1));
    expect(perf.marks).toHaveLength(0);
    expect(perf.measures).toHaveLength(0);
    expect(instr.perStageMeans()["inputHandling"]).toBeCloseTo(1, 5);
  });

  it("returns the callback's return value unchanged", () => {
    const perf = fakePerformance();
    const instr = new FrameInstrumentation({ performance: perf });
    const result = instr.timeStage("overlayRedraw", () => 42);
    expect(result).toBe(42);
  });
});
