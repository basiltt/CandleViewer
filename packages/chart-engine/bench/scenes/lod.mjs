// THROWAWAY PROTOTYPE (E06-K02). LOD ladder for candles per
// docs/plan/26-chart-engine-design.md §3.6: L0 full OHLC bodies+wicks
// (barSpacing >= 3px), L1 bodies only (>= 1.5px), L2 min/max column strip
// (below), with +/-15% hysteresis so slow zooming does not flicker.
export const LOD_L0_THRESHOLD_PX = 3;
export const LOD_L1_THRESHOLD_PX = 1.5;
export const HYSTERESIS = 0.15;

/**
 * Selects the next LOD level given the current barSpacing and the
 * previously-selected level, applying a +/-15% hysteresis band around each
 * threshold: once at a level, `barSpacing` must cross the threshold by more
 * than the band before switching, so noise near the boundary doesn't flap.
 * @param {number} barSpacingPx
 * @param {"L0"|"L1"|"L2"|null} previousLevel
 * @returns {"L0"|"L1"|"L2"}
 */
export function selectLod(barSpacingPx, previousLevel) {
  const upperL0 = LOD_L0_THRESHOLD_PX * (1 - HYSTERESIS); // must drop below this to leave L0
  const lowerL0Enter = LOD_L0_THRESHOLD_PX * (1 + HYSTERESIS); // must rise above this to enter L0
  const upperL1 = LOD_L1_THRESHOLD_PX * (1 - HYSTERESIS);
  const lowerL1Enter = LOD_L1_THRESHOLD_PX * (1 + HYSTERESIS);

  if (previousLevel === "L0") {
    if (barSpacingPx >= upperL0) return "L0";
    return barSpacingPx >= LOD_L1_THRESHOLD_PX ? "L1" : "L2";
  }
  if (previousLevel === "L1") {
    if (barSpacingPx >= lowerL0Enter) return "L0";
    if (barSpacingPx >= upperL1) return "L1";
    return "L2";
  }
  if (previousLevel === "L2") {
    if (barSpacingPx >= lowerL0Enter) return "L0";
    if (barSpacingPx >= lowerL1Enter) return "L1";
    return "L2";
  }
  // No previous level (first frame): plain threshold, no hysteresis to apply yet.
  if (barSpacingPx >= LOD_L0_THRESHOLD_PX) return "L0";
  if (barSpacingPx >= LOD_L1_THRESHOLD_PX) return "L1";
  return "L2";
}

/**
 * Min/max-preserving per-pixel-column reduction for L2 (§3.6: "spikes never
 * disappear — a correctness requirement, not a cosmetic one"). Emits one
 * column per pixel: min-low, max-high, first-open, last-close, summed volume.
 * @param {import("./bar-store.mjs").BarStore} store
 * @param {number} fromIndex inclusive
 * @param {number} toIndex exclusive
 * @param {number} columns number of pixel columns to reduce into
 */
export function decimateMinMax(store, fromIndex, toIndex, columns) {
  const clampedFrom = Math.max(0, Math.floor(fromIndex));
  const clampedTo = Math.min(store.length, Math.ceil(toIndex));
  const total = clampedTo - clampedFrom;
  const out = [];
  if (total <= 0 || columns <= 0) return out;
  const barsPerColumn = total / columns;

  for (let col = 0; col < columns; col += 1) {
    const start = clampedFrom + Math.floor(col * barsPerColumn);
    const end = Math.min(clampedTo, clampedFrom + Math.floor((col + 1) * barsPerColumn));
    if (start >= end) continue;
    let lo = store.low[start];
    let hi = store.high[start];
    let vol = 0;
    for (let i = start; i < end; i += 1) {
      if (store.low[i] < lo) lo = store.low[i];
      if (store.high[i] > hi) hi = store.high[i];
      vol += store.volume[i];
    }
    out.push({
      startIndex: start,
      endIndex: end,
      open: store.open[start],
      close: store.close[end - 1],
      low: lo,
      high: hi,
      volume: vol,
    });
  }
  return out;
}
