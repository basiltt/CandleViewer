import { describe, expect, it } from "vitest";
import { BarStore } from "../../../bench/scenes/bar-store.mjs";

function bar(i: number) {
  return { tOpenMs: i * 60_000, o: i, h: i + 5, l: i - 5, c: i + 1, v: 100 + i };
}

describe("BarStore (E06-K02 throwaway prototype)", () => {
  it("appends bars and reports the affected index range", () => {
    const store = new BarStore({ capacity: 4 });
    const r1 = store.appendBars([bar(0), bar(1)]);
    expect(r1).toEqual({ from: 0, to: 2 });
    const r2 = store.appendBars([bar(2)]);
    expect(r2).toEqual({ from: 2, to: 3 });
    expect(store.length).toBe(3);
  });

  it("doubles capacity rather than growing per-bar, preserving existing data", () => {
    const store = new BarStore({ capacity: 2 });
    const bars = Array.from({ length: 10 }, (_, i) => bar(i));
    store.appendBars(bars);
    expect(store.length).toBe(10);
    expect(store.capacity).toBeGreaterThanOrEqual(10);
    // Capacity growth must be a power-of-two multiple of the initial capacity.
    expect(Math.log2(store.capacity / 2)).toBeCloseTo(Math.round(Math.log2(store.capacity / 2)));
    for (let i = 0; i < 10; i += 1) {
      // Non-null: index is within the just-appended range (noUncheckedIndexedAccess).
      expect((store.open as Float32Array)[i] as number).toBe(i);
      expect((store.high as Float32Array)[i] as number).toBe(i + 5);
    }
  });

  it("keeps a monotone index->time map", () => {
    const store = new BarStore({ capacity: 8 });
    store.appendBars(Array.from({ length: 5 }, (_, i) => bar(i)));
    for (let i = 1; i < 5; i += 1) {
      expect(store.timeAt(i)).toBeGreaterThan(store.timeAt(i - 1) as number);
    }
  });

  it("clamps timeAt to the stored range", () => {
    const store = new BarStore({ capacity: 4 });
    store.appendBars([bar(0), bar(1)]);
    expect(store.timeAt(-1)).toBe(store.timeAt(0));
    expect(store.timeAt(99)).toBe(store.timeAt(1));
  });
});
