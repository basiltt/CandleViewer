// E13-K01 SPIKE — data loaders shared by bench + parity dump (throwaway).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { generateBars } from "../fixtures/bars.mjs";

const ROOT = fileURLToPath(new URL("../../../../", import.meta.url));

/** Seeded synthetic 1m model (same generator/seed family as the E06-K01/E11 harness). Ticks -> $ at 0.01. */
export function syntheticBars(count, seed = 20260928) {
  return generateBars({ seed, count }).map((b) => ({ t: b.tOpenMs, o: b.o / 100, h: b.h / 100, l: b.l / 100, c: b.c / 100, v: b.v / 1000 }));
}

/**
 * Recorded-fixture window: packages/fixtures/bybit/2026-10-05/rest/kline_BTCUSDT_1_page{0,1,2}.json
 * (450 unique 1m bars). The fixture has no gap, so a 15-minute hole is punched at bar 200 to force
 * densify() to synthesise flat bars — stated in the finding note.
 */
export function recordedBars({ punchGap = true } = {}) {
  const m = new Map();
  for (let p = 0; p < 3; p += 1) {
    const j = JSON.parse(readFileSync(`${ROOT}packages/fixtures/bybit/2026-10-05/rest/kline_BTCUSDT_1_page${p}.json`, "utf8"));
    for (const r of j.result.list) m.set(Number(r[0]), { t: Number(r[0]), o: Number(r[1]), h: Number(r[2]), l: Number(r[3]), c: Number(r[4]), v: Number(r[5]) });
  }
  let bars = [...m.values()].sort((a, b) => a.t - b.t);
  if (punchGap) bars = bars.filter((_, i) => i < 200 || i >= 215);
  return bars;
}
