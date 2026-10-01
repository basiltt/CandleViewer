// THROWAWAY PROTOTYPE (E06-K03). Footprint LOD ladder using E06-D01's
// LOD_PROFILE_M0 (docs/design/E06/E06-D01.md §2): thresholds are on cell
// height in CSS px. Down-switch uses the 0.85 band, up-switch the full
// threshold. Shedding text never drops or alters a cell (L2 = colour only).
export const FP_LOD = {
  L0: { minHeightPx: 12, downSwitchPx: 10.2 },
  L1: { minHeightPx: 10, downSwitchPx: 8.5 },
  L2: { minHeightPx: 6, downSwitchPx: 5.1 },
};
const ORDER = ["L0", "L1", "L2", "L3"];

/** @param {number} cellHeightPx @param {"L0"|"L1"|"L2"|"L3"|null} prev */
export function selectFootprintLod(cellHeightPx, prev) {
  if (prev === null) {
    if (cellHeightPx >= FP_LOD.L0.minHeightPx) return "L0";
    if (cellHeightPx >= FP_LOD.L1.minHeightPx) return "L1";
    if (cellHeightPx >= FP_LOD.L2.minHeightPx) return "L2";
    return "L3";
  }
  // Leave the current level only past its down-switch; enter higher levels
  // only at the full threshold.
  let idx = ORDER.indexOf(prev);
  while (idx > 0 && cellHeightPx >= FP_LOD[ORDER[idx - 1]].minHeightPx) idx -= 1;
  while (idx < 3 && cellHeightPx < FP_LOD[ORDER[idx]].downSwitchPx) idx += 1;
  return ORDER[idx];
}

/** Numbers drawn per cell at a level: L0 two (bid, ask), L1 one (delta). */
export const numbersAtLod = (lod) => (lod === "L0" ? 2 : lod === "L1" ? 1 : 0);

/** Full (E06-D01 §4) or compact (1.2K) formatting. */
export function formatVolume(v, mode = "full") {
  const n = Math.round(v);
  if (mode === "compact" && Math.abs(n) >= 1000) {
    const k = Math.abs(n) / 1000;
    return `${n < 0 ? "-" : ""}${k >= 100 ? Math.round(k) : k.toFixed(1)}K`;
  }
  return n.toLocaleString("en-US");
}

export function formatDelta(d, mode = "full") {
  const glyph = d >= 0 ? "▲" : "▼";
  const body = formatVolume(Math.abs(d), mode);
  return `${glyph}${d >= 0 ? "+" : "-"}${body}`;
}
