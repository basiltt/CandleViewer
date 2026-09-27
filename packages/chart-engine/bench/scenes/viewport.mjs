// THROWAWAY PROTOTYPE (E06-K02). Viewport/transform math per
// docs/plan/26-chart-engine-design.md §3.5: bar-index-space pan/zoom,
// cursor-anchored zoom, momentum with exponential decay.
export const MIN_BAR_SPACING_PX = 0.05;
export const MAX_BAR_SPACING_PX = 200;
export const MOMENTUM_TAU_MS = 120;
export const MOMENTUM_STOP_PX_PER_MS = 0.02;

export function clampBarSpacing(px) {
  if (px < MIN_BAR_SPACING_PX) return MIN_BAR_SPACING_PX;
  if (px > MAX_BAR_SPACING_PX) return MAX_BAR_SPACING_PX;
  return px;
}

/**
 * Viewport state in bar-index space: `rightOffset` is the bar index (may be
 * fractional) at the right edge of the plot; `barSpacing` is px/bar.
 */
export class Viewport {
  /** @param {{ plotWidthPx: number, barSpacing?: number, rightOffset?: number }} opts */
  constructor(opts) {
    this.plotWidthPx = opts.plotWidthPx;
    this.barSpacing = clampBarSpacing(opts.barSpacing ?? 6);
    this.rightOffset = opts.rightOffset ?? 0;
    /** px/ms, signed (positive = scrolling toward newer bars) */
    this.velocityPxPerMs = 0;
  }

  get visibleBarCount() {
    return this.plotWidthPx / this.barSpacing;
  }

  get leftIndex() {
    return this.rightOffset - this.visibleBarCount;
  }

  /** Bar-index -> screen-x (px from the left edge of the plot). */
  indexToScreen(barIndex) {
    return this.plotWidthPx - (this.rightOffset - barIndex) * this.barSpacing;
  }

  /** Screen-x -> bar-index (inverse of indexToScreen). */
  screenToIndex(screenX) {
    return this.rightOffset - (this.plotWidthPx - screenX) / this.barSpacing;
  }

  /**
   * Pans by a pixel delta in bar-index space (dxPx > 0 moves the view toward
   * older bars, matching a rightward drag revealing history to the left).
   */
  panByPx(dxPx) {
    this.rightOffset -= dxPx / this.barSpacing;
  }

  /**
   * Cursor-anchored zoom: the bar index under `anchorScreenX` is invariant
   * before and after the spacing change (§3.5 "the world coordinate under
   * the anchor is invariant").
   * @param {number} newBarSpacing
   * @param {number} anchorScreenX
   */
  zoomTo(newBarSpacing, anchorScreenX) {
    const anchorIndex = this.screenToIndex(anchorScreenX);
    this.barSpacing = clampBarSpacing(newBarSpacing);
    // Solve rightOffset so anchorIndex maps back to the same screen X.
    this.rightOffset = anchorIndex + (this.plotWidthPx - anchorScreenX) / this.barSpacing;
  }

  /** Starts momentum after a drag release, given the release velocity (px/ms). */
  applyMomentumImpulse(velocityPxPerMs) {
    this.velocityPxPerMs = velocityPxPerMs;
  }

  /**
   * Integrates momentum for `dtMs` of elapsed time using exponential decay
   * (`v *= exp(-dt/tau)`), terminating below the stop threshold. dt-based,
   * not frame-count-based, so it is fps-independent (ticket's "same outcome
   * at 30 and 144 fps" unit-test requirement).
   */
  stepMomentum(dtMs) {
    if (Math.abs(this.velocityPxPerMs) < MOMENTUM_STOP_PX_PER_MS) {
      this.velocityPxPerMs = 0;
      return;
    }
    this.panByPx(this.velocityPxPerMs * dtMs);
    this.velocityPxPerMs *= Math.exp(-dtMs / MOMENTUM_TAU_MS);
    if (Math.abs(this.velocityPxPerMs) < MOMENTUM_STOP_PX_PER_MS) {
      this.velocityPxPerMs = 0;
    }
  }

  get isMomentumActive() {
    return this.velocityPxPerMs !== 0;
  }
}
