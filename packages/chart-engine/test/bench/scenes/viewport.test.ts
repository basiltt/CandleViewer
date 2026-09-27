import { describe, expect, it } from "vitest";
import {
  Viewport,
  clampBarSpacing,
  MIN_BAR_SPACING_PX,
  MAX_BAR_SPACING_PX,
  MOMENTUM_STOP_PX_PER_MS,
} from "../../../bench/scenes/viewport.mjs";

describe("Viewport (E06-K02 throwaway prototype) — §3.5 transform math", () => {
  it("clamps barSpacing to [0.05, 200] px", () => {
    expect(clampBarSpacing(0.001)).toBe(MIN_BAR_SPACING_PX);
    expect(clampBarSpacing(9999)).toBe(MAX_BAR_SPACING_PX);
    expect(clampBarSpacing(10)).toBe(10);
  });

  it("indexToScreen/screenToIndex round-trip", () => {
    const vp = new Viewport({ plotWidthPx: 1000, barSpacing: 5, rightOffset: 500 });
    for (const idx of [0, 100, 499.5, 500]) {
      const screen = vp.indexToScreen(idx);
      expect(vp.screenToIndex(screen)).toBeCloseTo(idx, 9);
    }
  });

  it("keeps the world coordinate under the cursor invariant during zoom", () => {
    const vp = new Viewport({ plotWidthPx: 800, barSpacing: 4, rightOffset: 1000 });
    const anchorScreenX = 300;
    const anchorIndexBefore = vp.screenToIndex(anchorScreenX);
    vp.zoomTo(20, anchorScreenX);
    const anchorIndexAfter = vp.screenToIndex(anchorScreenX);
    expect(anchorIndexAfter).toBeCloseTo(anchorIndexBefore, 6);
  });

  it("pans by the expected number of bars for a given pixel delta", () => {
    const vp = new Viewport({ plotWidthPx: 800, barSpacing: 10, rightOffset: 100 });
    vp.panByPx(100); // 100px / 10px-per-bar = 10 bars
    expect(vp.rightOffset).toBeCloseTo(90, 9);
  });

  it("momentum decays exponentially and terminates below the stop threshold", () => {
    const vp = new Viewport({ plotWidthPx: 800, barSpacing: 5, rightOffset: 0 });
    vp.applyMomentumImpulse(1); // 1 px/ms
    let steps = 0;
    while (vp.isMomentumActive && steps < 100_000) {
      vp.stepMomentum(16.7);
      steps += 1;
    }
    expect(vp.isMomentumActive).toBe(false);
    expect(Math.abs(vp.velocityPxPerMs)).toBeLessThan(MOMENTUM_STOP_PX_PER_MS + 1e-9);
    expect(steps).toBeGreaterThan(0);
  });

  it("momentum decay is dt-based: same outcome at 30fps and 144fps step sizes", () => {
    const vpSlow = new Viewport({ plotWidthPx: 800, barSpacing: 5, rightOffset: 10_000 });
    const vpFast = new Viewport({ plotWidthPx: 800, barSpacing: 5, rightOffset: 10_000 });
    vpSlow.applyMomentumImpulse(2);
    vpFast.applyMomentumImpulse(2);

    const totalMs = 1000;
    const dtSlow = 1000 / 30;
    const dtFast = 1000 / 144;

    let elapsed = 0;
    while (elapsed < totalMs) {
      vpSlow.stepMomentum(dtSlow);
      elapsed += dtSlow;
    }
    elapsed = 0;
    while (elapsed < totalMs) {
      vpFast.stepMomentum(dtFast);
      elapsed += dtFast;
    }

    // Both integrate the same physical motion over the same wall-clock
    // duration, so the resulting position should match closely regardless
    // of step granularity — within a tolerance that accounts for Euler
    // discretisation error at a coarser (30fps) step size.
    const diff = Math.abs(vpSlow.rightOffset - vpFast.rightOffset);
    expect(diff).toBeLessThan(10);
  });
});
