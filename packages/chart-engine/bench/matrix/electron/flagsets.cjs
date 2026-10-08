// E06-T01 Electron GPU flag sets under evaluation. NOTHING here is invented:
//   default = Electron's own defaults (no extra switches) — the control arm.
//   tuned   = exactly the set the shipped shell already applies, from
//             apps/desktop/src/main/gpu.ts, rationale in apps/desktop/GPU_FLAGS.md
//             (E10-K01). That doc says it "is designed to be revisited the moment
//             E06-T01 lands a real measurement" — this matrix is that measurement.
// The winner is the recommended configuration handed to E10 (ticket DoD). Add a
// flag set ONLY by adding a justified row to apps/desktop/GPU_FLAGS.md first.
// Deliberately NOT applied (per GPU_FLAGS.md): --disable-gpu-sandbox, --ignore-gpu-blocklist.
"use strict";

/** @type {Record<string, { description: string, flags: string[], switches: Array<[string, string?]> }>} */
const ELECTRON_FLAGSETS = {
  default: {
    description: "Electron defaults, no extra command-line switches",
    flags: [],
    switches: [],
  },
  tuned: {
    description: "apps/desktop/GPU_FLAGS.md set (E10-K01)",
    flags: ["--enable-gpu-rasterization", "--disable-features=CalculateNativeWinOcclusion"],
    switches: [["enable-gpu-rasterization"], ["disable-features", "CalculateNativeWinOcclusion"]],
  },
};

exports.ELECTRON_FLAGSETS = ELECTRON_FLAGSETS;
