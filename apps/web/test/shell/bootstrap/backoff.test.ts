import { describe, expect, it } from "vitest";
import { backoffDelayWithJitter, backoffStepFor } from "../../../src/shell/bootstrap/backoff.js";

describe("backoffStepFor", () => {
  it("matches the §9.2 table for attempts 1..6", () => {
    expect(backoffStepFor(1)).toEqual({ delayMs: 500, jitterMs: 250 });
    expect(backoffStepFor(2)).toEqual({ delayMs: 1_000, jitterMs: 500 });
    expect(backoffStepFor(3)).toEqual({ delayMs: 2_000, jitterMs: 1_000 });
    expect(backoffStepFor(4)).toEqual({ delayMs: 5_000, jitterMs: 2_000 });
    expect(backoffStepFor(5)).toEqual({ delayMs: 10_000, jitterMs: 5_000 });
    expect(backoffStepFor(6)).toEqual({ delayMs: 30_000, jitterMs: 10_000 });
  });

  it("clamps attempt 7+ to the 30 s row, never growing further", () => {
    expect(backoffStepFor(7)).toEqual({ delayMs: 30_000, jitterMs: 10_000 });
    expect(backoffStepFor(100)).toEqual({ delayMs: 30_000, jitterMs: 10_000 });
  });

  it("clamps attempt 0 or negative to the first row", () => {
    expect(backoffStepFor(0)).toEqual({ delayMs: 500, jitterMs: 250 });
    expect(backoffStepFor(-3)).toEqual({ delayMs: 500, jitterMs: 250 });
  });
});

describe("backoffDelayWithJitter", () => {
  it("stays within [delay - jitter, delay + jitter] for every attempt", () => {
    for (let attempt = 1; attempt <= 8; attempt += 1) {
      const { delayMs, jitterMs } = backoffStepFor(attempt);
      for (const random of [0, 0.25, 0.5, 0.75, 1]) {
        const value = backoffDelayWithJitter(attempt, () => random);
        expect(value).toBeGreaterThanOrEqual(Math.max(0, delayMs - jitterMs));
        expect(value).toBeLessThanOrEqual(delayMs + jitterMs);
      }
    }
  });

  it("never returns a negative delay", () => {
    const value = backoffDelayWithJitter(1, () => 0);
    expect(value).toBeGreaterThanOrEqual(0);
  });

  it("is deterministic given an injected random source", () => {
    const a = backoffDelayWithJitter(3, () => 0.5);
    const b = backoffDelayWithJitter(3, () => 0.5);
    expect(a).toBe(b);
  });
});
