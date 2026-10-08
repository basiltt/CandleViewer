// E06-T01 — B5 "combined scene" (THROWAWAY PROTOTYPE COMPOSITION, bench only).
//
// This is the scene R0 exit criterion 4 (docs/plan/30-release-roadmap.md §4.3)
// is stated against, so its composition is fixed and documented here:
//
//   Layer                         Source                         Draw calls
//   ---------------------------   ----------------------------   ----------
//   A  100k-bar model, LOD ladder bench/scenes/scene-a.mjs       4
//   B  footprint cells, SDF text  bench/scenes/scene-b.mjs       3
//   C  200-row depth heatmap ring bench/scenes/scene-c.mjs       <= 4 (ring ranges)
//   +  3 synthetic indicator series (seeded SMA-like polylines)  3 (1 per series)
//   +  50 order lines (seeded price levels, 1 instanced batch)   1
//   +  order-line label batch (50 SDF labels, 1 batch)           1
//   +  shared composite/present (A/B/C each report 1; counted once, so -2)
//   ---------------------------------------------------------------------
//   expected total <= 18, hard gate: <= 40 draw calls (B5 gate)
//
// GATES (06-performance-and-load-standard.md §4 / ticket): p95 frame time
// <= 16.7 ms AND <= 40 draw calls. Roadmap §4.3 bar: p50 >= 60 fps (<= 16.67 ms)
// and p95 >= 55 fps (<= 18.18 ms) — exported so compare-matrix states both.
//
// Stage merge rule: per-frame stage costs of the three layers are SUMMED, except
// `compositePresent` which is the MAX (one swap chain present per frame, not
// three). The indicator and order-line stages add to `overlayRedraw`/`paneRedraw`.
//
// Seeding: every random quantity derives from `seed` (mulberry32), the K01
// fixture supplies bars + footprint cells, so identical seed + fixture =>
// identical composition on every runtime.
import { SceneA } from "../../scenes/scene-a.mjs";
import { SceneB } from "../../scenes/scene-b.mjs";
import { SceneC } from "../../scenes/scene-c.mjs";
import { mulberry32 } from "../../fixtures/rng.mjs";

export const B5_GATES = Object.freeze({
  p95FrameMs: 16.7,
  maxDrawCalls: 40,
  // docs/plan/30-release-roadmap.md §4.3 exit criterion 4.
  exitCriterion4: Object.freeze({ p50FrameMs: 1000 / 60, p95FrameMs: 1000 / 55 }),
});

export const B5_COMPOSITION = Object.freeze({
  indicatorSeries: 3,
  orderLines: 50,
  layers: ["A:bars+LOD", "B:footprint+SDF", "C:heatmap-ring", "indicators", "order-lines"],
});

// Modelled GPU cost (no real GL inside the scene; the matrix page adds REAL GL
// work on top via gl-load.mjs). Constants follow scene-a's convention.
const COST_PER_INDICATOR_POINT_MS = 0.00035;
const COST_PER_ORDER_LINE_MS = 0.004;
const COST_ORDER_LABELS_MS = 0.12;

/** @implements {import("../../scene.mjs").BenchScene} */
export class SceneB5 {
  /** @param {{ seed?: number, footprintEveryMs?: number }} [opts] */
  constructor(opts = {}) {
    this.seed = opts.seed ?? 20260928;
    this.footprintEveryMs = opts.footprintEveryMs ?? 500;
    this.a = new SceneA();
    this.b = new SceneB();
    this.c = new SceneC({ seed: this.seed });
    this.indicators = /** @type {Float32Array[]} */ ([]);
    this.orderLinePrices = new Float32Array(B5_COMPOSITION.orderLines);
    this._lastFootprintT = -Infinity;
    this._stats = null;
    this._indicatorPointsLast = 0;
  }

  /** @param {import("../../fixtures/index.mjs").M0Fixture} fixture */
  init(fixture) {
    this.a.init(fixture);
    this.b.init(fixture);
    this.c.init();
    const rng = mulberry32(this.seed ^ 0x51ed270b);
    const bars = fixture.bars;
    const n = bars.length;
    // 3 synthetic series (fast/slow/volatility-band style): EMA-ish of close
    // with seeded smoothing so they are deterministic but not identical.
    this.indicators = [];
    for (let s = 0; s < B5_COMPOSITION.indicatorSeries; s += 1) {
      const alpha = 0.02 + rng() * 0.2;
      const series = new Float32Array(n);
      let v = bars[0]?.c ?? 0;
      for (let i = 0; i < n; i += 1) {
        v += alpha * ((bars[i]?.c ?? v) - v);
        series[i] = v;
      }
      this.indicators.push(series);
    }
    const lo = Math.min(...bars.slice(0, 2000).map((b) => b.l));
    const hi = Math.max(...bars.slice(0, 2000).map((b) => b.h));
    for (let i = 0; i < this.orderLinePrices.length; i += 1) {
      this.orderLinePrices[i] = lo + rng() * (hi - lo);
    }
  }

  /**
   * @param {number} tMs
   * @param {import("../../driver.mjs").DriverEvent | null} input
   */
  step(tMs, input) {
    if (tMs < this._lastFootprintT) this._lastFootprintT = -Infinity; // new repetition
    this.a.step(tMs, input);
    this.c.step(tMs, input);
    // B5 driver (driver.mjs) has no footprint events; B5 means "footprint hold with
    // periodic updates", so synthesise the 500 ms rebuild cadence from B3.
    /** @type {import("../../driver.mjs").DriverEvent} */
    const fp = { tMs, kind: "footprintHold", payload: {} };
    if (tMs - this._lastFootprintT >= this.footprintEveryMs) {
      this._lastFootprintT = tMs;
      fp.payload = { rebuild: 1 };
    }
    this.b.step(tMs, fp);

    // Indicators: real CPU window walk over the visible bar range (checksum
    // defeats dead-code elimination), model the GPU polyline cost.
    const t0 = performance.now();
    const sa = this.a.extendedStats();
    const win = this.a._scratchWindow;
    let sum = 0;
    let points = 0;
    for (const series of this.indicators) {
      const from = win.fromIndex;
      const to = Math.min(series.length, win.toIndex);
      const stride = Math.max(1, Math.floor((to - from) / 2000)); // decimated to <=2000 pts
      for (let i = from; i < to; i += stride) {
        sum += series[i];
        points += 1;
      }
    }
    this._indicatorPointsLast = points;
    this._checksum = sum;
    const indicatorCpuMs = performance.now() - t0;

    const sA = this.a.stats();
    const sB = this.b.stats();
    const sC = this.c.stats();
    const orderMs = B5_COMPOSITION.orderLines * COST_PER_ORDER_LINE_MS + COST_ORDER_LABELS_MS;
    const indicatorMs = points * COST_PER_INDICATOR_POINT_MS + indicatorCpuMs;

    /** @type {Record<string, number>} */
    const stage = {};
    for (const k of Object.keys({ ...sA.perStageMs, ...sB.perStageMs, ...sC.perStageMs })) {
      const parts = [sA.perStageMs[k] ?? 0, sB.perStageMs[k] ?? 0, sC.perStageMs[k] ?? 0];
      stage[k] = k === "compositePresent" ? Math.max(...parts) : parts[0] + parts[1] + parts[2];
    }
    stage.overlayRedraw = (stage.overlayRedraw ?? 0) + orderMs;
    stage.paneRedraw = (stage.paneRedraw ?? 0) + indicatorMs;

    const drawCalls =
      sA.drawCalls +
      sB.drawCalls +
      sC.drawCalls +
      B5_COMPOSITION.indicatorSeries +
      2 /* order lines + labels */ -
      2; /* A/B/C each count their own composite; one present per frame */
    this._stats = {
      frameTimeMs: Object.values(stage).reduce((acc, v) => acc + v, 0),
      drawCalls,
      uploadedBytesPerSec: sA.uploadedBytesPerSec + sB.uploadedBytesPerSec + sC.uploadedBytesPerSec,
      textureMemMB: sA.textureMemMB + sB.textureMemMB + sC.textureMemMB,
      perStageMs: stage,
    };
    this._visibleBars = sa.visibleBars;
  }

  stats() {
    return (
      this._stats ?? {
        frameTimeMs: 0,
        drawCalls: 0,
        uploadedBytesPerSec: 0,
        textureMemMB: 0,
        perStageMs: {},
      }
    );
  }

  /** Composition counters for the report (proves what was measured). */
  describe() {
    return {
      ...B5_COMPOSITION,
      visibleBars: this._visibleBars ?? 0,
      indicatorPointsPerFrame: this._indicatorPointsLast,
      orderLines: this.orderLinePrices.length,
      gates: B5_GATES,
    };
  }

  dispose() {
    this.a.dispose();
    this.b.dispose();
    this.c.dispose();
    this.indicators = [];
  }
}
