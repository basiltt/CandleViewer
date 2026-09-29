import { describe, expect, it } from "vitest";
import {
  percentile,
  summarizePercentiles,
  isAdmissible,
  medianOfP95,
  DEFAULT_REPETITIONS,
} from "../../bench/stats.mjs";

describe("percentile / summarizePercentiles", () => {
  it("computes p50/p95/p99 on a known distribution", () => {
    const values = Array.from({ length: 100 }, (_, i) => i + 1); // 1..100
    expect(percentile(values, 50)).toBe(50);
    expect(percentile(values, 95)).toBe(95);
    expect(percentile(values, 99)).toBe(99);
  });

  it("returns 0 for an empty array without throwing", () => {
    expect(summarizePercentiles([])).toEqual({ p50: 0, p95: 0, p99: 0 });
  });

  it("does not mutate the input array", () => {
    const values = [5, 1, 3];
    percentile(values, 50);
    expect(values).toEqual([5, 1, 3]);
  });
});

describe("admissibility rule (ticket: < 3 reps -> not admissible for ADR evidence)", () => {
  it("defaults repetitions to 3", () => {
    expect(DEFAULT_REPETITIONS).toBe(3);
  });

  it("is admissible at exactly 3 repetitions", () => {
    expect(isAdmissible(3)).toBe(true);
  });

  it("is not admissible below 3 repetitions", () => {
    expect(isAdmissible(2)).toBe(false);
    expect(isAdmissible(1)).toBe(false);
    expect(isAdmissible(0)).toBe(false);
  });
});

describe("medianOfP95 (ticket §7.4: gate compares median of repeated p95s)", () => {
  it("returns the middle value for an odd count", () => {
    expect(medianOfP95([10, 30, 20])).toBe(20);
  });

  it("averages the two middle values for an even count", () => {
    expect(medianOfP95([10, 20, 30, 40])).toBe(25);
  });

  it("returns 0 for an empty array", () => {
    expect(medianOfP95([])).toBe(0);
  });
});
