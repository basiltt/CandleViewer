import { describe, expect, it } from "vitest";
import { generateM0Fixture } from "../../../bench/fixtures/index.mjs";
import { SceneB5, B5_GATES, B5_COMPOSITION } from "../../../bench/matrix/scenes/b5-combined.mjs";
import {
  StormStores,
  encodeMessage,
  evaluateStorm,
  runStormInline,
  STORM,
} from "../../../bench/matrix/scenes/b7-storm.mjs";
import { percentile } from "../../../bench/stats.mjs";
import { mulberry32 } from "../../../bench/fixtures/rng.mjs";
import { captureVersionManifest, missingManifestFields } from "../../../bench/machine.mjs";
import { ELECTRON_FLAGSETS } from "../../../bench/matrix/electron/flagsets.cjs";
import { soakBuckets } from "../../../bench/matrix/frame-stats.mjs";

describe("B5 combined scene", () => {
  const fixture = generateM0Fixture({ seed: 7, barCount: 500 });
  it("composes A+B+C + 3 indicators + 50 order lines within the draw-call gate, deterministically", () => {
    const run = () => {
      const s = new SceneB5({ seed: 7 });
      s.init(fixture);
      let maxDraw = 0;
      for (let t = 0; t < 600; t += 16) {
        s.step(t, { tMs: t, kind: "pan", payload: { dxPx: 5 } });
        maxDraw = Math.max(maxDraw, s.stats().drawCalls);
      }
      const d = s.describe();
      const lines = Array.from(s.orderLinePrices.slice(0, 3));
      s.dispose();
      return { maxDraw, d, lines };
    };
    const a = run();
    expect(a.maxDraw).toBeLessThanOrEqual(B5_GATES.maxDrawCalls);
    expect(a.d.indicatorSeries).toBe(B5_COMPOSITION.indicatorSeries);
    expect(a.d.orderLines).toBe(50);
    expect(run().lines).toEqual(a.lines);
  });
});

describe("B7 storm", () => {
  it("detects a dropped message (sequence gap) and a duplicate", () => {
    const rng = mulberry32(1);
    const st = new StormStores();
    st.decodeAndApply(encodeMessage(rng, 0, 0));
    st.decodeAndApply(encodeMessage(rng, 0, 2)); // seq 1 dropped
    st.decodeAndApply(encodeMessage(rng, 0, 2)); // duplicate
    expect(st.gaps).toBe(1);
    expect(st.duplicates).toBe(1);
    const v = evaluateStorm(
      { sent: 3, applied: st.applied, gaps: st.gaps, duplicates: st.duplicates, decodeMs: [0.1] },
      percentile,
    );
    expect(v.pass).toBe(false);
  });
  it("inline run on a fake clock applies every message exactly once", async () => {
    let now = 0;
    const r = await runStormInline({
      durationMs: 500,
      seed: 3,
      now: () => now,
      sleep: async (ms: number) => {
        now += ms;
      },
    });
    expect(r.sent).toBe(Math.floor(500 / (1000 / STORM.msgsPerSecPerStore)) * STORM.storeCount);
    expect(r.applied).toBe(r.sent);
    expect(evaluateStorm(r, percentile).pass).toBe(true);
  });
});

describe("version manifest / flag sets / soak buckets", () => {
  it("requires WebView2 for tauri and Electron+Chromium for electron", () => {
    const m = captureVersionManifest({ runtime: "tauri", useOsGpuProbe: false });
    expect(missingManifestFields(m)).toEqual(["tauri", "webview2"]);
    const e = captureVersionManifest({
      runtime: "electron",
      useOsGpuProbe: false,
      versions: { electron: "41", chromium: "1" },
    });
    expect(missingManifestFields(e)).toEqual([]);
  });
  it("tuned flag set equals the documented E10-K01 set and default adds nothing", () => {
    expect(ELECTRON_FLAGSETS["default"]?.flags).toEqual([]);
    expect(ELECTRON_FLAGSETS["tuned"]?.flags).toEqual([
      "--enable-gpu-rasterization",
      "--disable-features=CalculateNativeWinOcclusion",
    ]);
  });
  it("soakBuckets exposes a per-minute trend", () => {
    const at = [0, 1000, 61_000, 62_000];
    const b = soakBuckets(at, [1, 40, 1, 1], [0, 61_000], [0.1, 0.3], 60_000);
    expect(b).toHaveLength(2);
    expect(b[0]?.outliers33).toBe(1);
    expect(b[1]?.texUploadMedianMs).toBe(0.3);
  });
});
