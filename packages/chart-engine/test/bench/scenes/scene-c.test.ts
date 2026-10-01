import { describe, expect, it } from "vitest";
import {
  Ring,
  FINE_COLS,
  ROWS,
  toHalf,
  sourceForAge,
  selectProfile,
  maxMagnitudeInto,
} from "../../../bench/scenes/heatmap-ring.mjs";
import {
  buildLut,
  swapHalves,
  lutIndex,
  intensity,
  decayFactor,
  legendTickColour,
  resolveToken,
} from "../../../bench/scenes/heatmap-lut.mjs";
import { SceneC, FULL_CAPS } from "../../../bench/scenes/scene-c.mjs";

const ev = { kind: "heatmapStream" };

describe("Ring", () => {
  it("wraps the cursor and yields two sub-quads at the wrap", () => {
    const r = new Ring(8, 4, 100);
    const col = new Uint16Array(4);
    for (let i = 0; i < 8; i += 1) r.writeColumn(i * 100, col);
    expect(r.writeCol).toBe(0);
    expect(r.ringWraps).toBe(1);
    expect(r.drawRanges()).toEqual([{ from: 0, to: 8 }]);
    r.writeColumn(800, col);
    r.writeColumn(900, col);
    expect(r.drawRanges()).toEqual([
      { from: 2, to: 8 },
      { from: 0, to: 2 },
    ]);
  });
  it("keeps colTime monotonic in draw order", () => {
    const r = new Ring(8, 2, 100);
    for (let i = 0; i < 13; i += 1) r.writeColumn(i * 100, new Uint16Array(2));
    const order = r
      .drawRanges()
      .flatMap((d: { from: number; to: number }) =>
        Array.from({ length: d.to - d.from }, (_, k) => r.colTime[d.from + k] ?? 0),
      );
    for (let i = 1; i < order.length; i += 1)
      expect(order[i] ?? 0).toBeGreaterThan(order[i - 1] ?? 0);
  });
  it("uploads exactly rows*2 bytes per column", () => {
    const r = new Ring(8, 512, 100);
    expect(r.writeColumn(0, new Uint16Array(512))).toBe(1024);
  });
  it("shift re-uploads only the newly exposed rows and clears them", () => {
    const r = new Ring(4, 8, 100);
    for (let c = 0; c < 4; c += 1) r.writeColumn(c, new Uint16Array(8).fill(7));
    const before = r.uploadedBytes;
    const res = r.shiftRows(2);
    expect(res).toEqual({ bytes: 2 * 4 * 2, rows: 2 });
    expect(r.uploadedBytes - before).toBe(16);
    // logical rows 6,7 are the new (cleared) band; 0..5 keep data
    for (let c = 0; c < 4; c += 1) {
      expect(r.texel(c, 7)).toBe(0);
      expect(r.texel(c, 6)).toBe(0);
      expect(r.texel(c, 0)).toBe(7);
    }
  });
  it("max-pools so a spike survives aggregation", () => {
    const dst = new Uint16Array([toHalf(0.1), 0]);
    maxMagnitudeInto(dst, new Uint16Array([toHalf(0.9), toHalf(-0.5)]));
    expect(dst[0]).toBe(toHalf(0.9));
    expect(dst[1]).toBe(toHalf(-0.5));
  });
  it("selects fine/coarse exactly at the age boundary", () => {
    expect(sourceForAge(FINE_COLS * 100 - 1)).toBe("fine");
    expect(sourceForAge(FINE_COLS * 100)).toBe("coarse");
  });
});

describe("LUT (E06-D02 §3)", () => {
  it("is 256x1 RGBA with token-derived endpoints", () => {
    const lut = buildLut("dark");
    expect(lut.byteLength).toBe(1024);
    const hex = (i: number) =>
      "#" +
      Array.from(lut.slice(i * 4, i * 4 + 3))
        .map((v) => v.toString(16).padStart(2, "0"))
        .join("")
        .toUpperCase();
    expect(hex(0)).toBe(resolveToken("color.heatmap.zero").toUpperCase());
    expect(hex(127)).toBe(resolveToken("color.heatmap.bid.5").toUpperCase());
    expect(hex(255)).toBe(resolveToken("color.heatmap.ask.5").toUpperCase());
    expect(hex(128)).toBe(resolveToken("color.heatmap.ask.1").toUpperCase());
  });
  it("swap is a slice swap, involutive", () => {
    const a = buildLut("dark");
    const b = swapHalves(buildLut("dark"));
    expect(Array.from(b.slice(4, 8))).toEqual(Array.from(a.slice(129 * 4, 129 * 4 + 4)));
    swapHalves(b);
    expect(Array.from(b)).toEqual(Array.from(a));
  });
  it("legend tick colour equals shader colour (round-trip)", () => {
    const lut = buildLut("dark");
    for (const v of [10, 100, 500, 1000]) {
      const idx = lutIndex(-v, 1000);
      expect(legendTickColour(lut, v, 1000, "ask")).toEqual(
        Array.from(lut.slice(idx * 4, idx * 4 + 3)),
      );
    }
  });
  it("log mapping resolves 10% depth above linear; decay follows tau", () => {
    expect(intensity(100, 1000, "log")).toBeGreaterThan(intensity(100, 1000, "linear"));
    expect(decayFactor(120)).toBeGreaterThan(0.85);
    expect(decayFactor(3600)).toBeLessThan(0.05);
    expect(decayFactor(5, true)).toBe(1);
  });
});

describe("SceneC", () => {
  it("B4 gates hold over 4 h trail (modelled GPU)", () => {
    const s = new SceneC({ trailMs: 4 * 3600_000 });
    s.init();
    const times: number[] = [];
    let last = 0;
    for (let t = 0; t < 5000; t += 1000 / 60) {
      s.step(t, Math.round(t) % 100 < 17 ? ev : null);
      times.push(s.stats().frameTimeMs);
      last = s.stats().uploadedBytesPerSec;
    }
    times.sort((a, b) => a - b);
    expect(times[Math.floor(times.length * 0.95)] ?? Infinity).toBeLessThanOrEqual(10);
    expect(last).toBeLessThanOrEqual(12 * 1024);
    expect(s.stats().textureMemMB).toBeLessThanOrEqual(20);
  });
  it("upload bytes per second are independent of trail length and message rate", () => {
    const rate = (o: object) => {
      const s = new SceneC(o);
      s.init();
      let r = 0;
      for (let i = 0; i < 60; i += 1) {
        s.step(i * 100, ev);
        r = s.stats().uploadedBytesPerSec;
      }
      return r;
    };
    const a = rate({ trailMs: 5 * 60_000 });
    expect(rate({ trailMs: 3600_000 })).toBe(a);
    expect(rate({ trailMs: 4 * 3600_000 })).toBe(a);
    expect(rate({ msgMult: 5 })).toBe(a);
  });
  it("price-origin shift uploads only new rows (counter-asserted)", () => {
    const s = new SceneC({ trailMs: 60_000 });
    s.init();
    s.step(0, ev);
    s.forceJumpRows = 10;
    const f0 = s.fine.uploadedBytes;
    s.step(100, ev);
    expect(s.fine.uploadedBytes - f0).toBe(10 * FINE_COLS * 2 + ROWS * 2);
    // GPU-side (modelled) portion of the shift frame; CPU shift time is wall-clock
    // and reported by the CLI (noisy under parallel vitest workers).
    const st = s.stats().perStageMs as Record<string, number>;
    expect((st["heatmapUpload"] ?? 0) + (st["paneRedraw"] ?? 0)).toBeLessThan(16);
    let t = 100;
    while (s.pendingCoarseShift !== 0) {
      t += 100;
      s.step(t, ev);
    }
    expect(s.c.rowsReuploaded).toBe(20);
  });
  it("theme change is exactly one 256x1 upload and no heatmap data", () => {
    const s = new SceneC({ trailMs: 60_000 });
    s.init();
    const before = s.fine.uploadedBytes + s.coarse.uploadedBytes;
    expect(s.swapConvention()).toMatchObject({ uploads: 1, bytes: 1024 });
    expect(s.fine.uploadedBytes + s.coarse.uploadedBytes).toBe(before);
  });
  it("context loss rebuilds from the data model without data loss", () => {
    const s = new SceneC({ trailMs: 60_000 });
    s.init();
    const snap = Array.from(s.fine.data.slice(0, 64));
    const r = s.loseContext();
    expect(r.fineColumnsIntact).toBe(s.fine.count);
    expect(Array.from(s.fine.data.slice(0, 64))).toEqual(snap);
  });
  it("capability gaps select reduced or degraded-2d", () => {
    expect(selectProfile(FULL_CAPS)).toBe("full");
    expect(selectProfile({ ...FULL_CAPS, OES_texture_float_linear: false })).toBe("reduced");
    expect(selectProfile({ ...FULL_CAPS, EXT_color_buffer_float: false })).toBe("degraded-2d");
    expect(selectProfile({ ...FULL_CAPS, r16fSampling: false })).toBe("degraded-2d");
  });
});
