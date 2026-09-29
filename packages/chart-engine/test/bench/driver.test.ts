import { describe, expect, it } from "vitest";
import { buildDriverScript, SCENARIOS } from "../../bench/driver.mjs";

describe("driver scripts (time-parameterised, not frame-parameterised)", () => {
  it("produces the same logical motion regardless of sampleHz (ticket: 30fps vs 144fps)", () => {
    const slow = buildDriverScript({ scenario: "B1", durationMs: 1000, sampleHz: 30 });
    const fast = buildDriverScript({ scenario: "B1", durationMs: 1000, sampleHz: 144 });
    const totalDx = (events: Array<{ payload?: { dxPx?: number } }>) =>
      events.reduce((sum, e) => sum + (e.payload?.dxPx ?? 0), 0);
    // Same total pan distance covered over the same wall-clock duration,
    // independent of how many samples were taken to get there.
    expect(totalDx(slow)).toBeCloseTo(1000, -1);
    expect(totalDx(fast)).toBeCloseTo(1000, -1);
  });

  it("builds a non-empty script for every named scenario", () => {
    for (const scenario of SCENARIOS) {
      const events = buildDriverScript({ scenario, durationMs: 500, sampleHz: 60 });
      expect(events.length).toBeGreaterThan(0);
    }
  });

  it("B2 sweeps pxPerBar monotonically from ~0.1 to ~50", () => {
    const events = buildDriverScript({ scenario: "B2", durationMs: 1000, sampleHz: 10 });
    const first = events[0]?.payload?.["pxPerBar"];
    const last = events[events.length - 1]?.payload?.["pxPerBar"];
    expect(first).toBeCloseTo(0.1, 1);
    expect(last).toBeGreaterThan(40);
  });

  it("B9 (cold init) emits exactly one event", () => {
    const events = buildDriverScript({ scenario: "B9", durationMs: 5000, sampleHz: 60 });
    expect(events).toHaveLength(1);
  });
});
