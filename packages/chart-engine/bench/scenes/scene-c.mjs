// THROWAWAY PROTOTYPE (E06-K04) - Scene C: 200-depth heatmap texture ring (B4/B10).
// Implements the E06-K01 BenchScene contract. No GPU here: ring/LUT/shift/quantise
// CPU work and upload byte counters are real; GPU draw/upload time is MODELLED
// (constants below, calibrated to 06-... section 4.3 "heatmap upload <= 2 ms").
import { mulberry32 } from "../fixtures/rng.mjs";
import {
  Ring,
  FINE_COLS,
  ROWS,
  COARSE_COLS,
  FINE_STEP_MS,
  toHalf,
  maxMagnitudeInto,
  selectProfile,
} from "./heatmap-ring.mjs";
import { buildLut, swapHalves, intensity, LOG_K } from "./heatmap-lut.mjs";

const GPU_UPLOAD_PER_KB = 0.004; // ms per KB texSubImage2D (driver copy + sync)
const GPU_QUAD = 0.05; // ms per textured quad (fill ~ viewport)
const BASE_OTHER_MS = 0.9;
const COARSE_SHIFT_ROWS_PER_TICK = 4;
export const FULL_CAPS = {
  webgl2: true,
  EXT_color_buffer_float: true,
  r16fSampling: true,
  OES_texture_float_linear: true,
  instancing: true,
  offscreenCanvasWorker: true,
};

export class SceneC {
  /**
   * @param {{coarseStepMs?:1000|2000, trailMs?:number, msgMult?:number, cadenceMs?:number,
   *   norm?:"colMax"|"global", mode?:"log"|"linear", caps?:object, seed?:number}} [o]
   */
  constructor(o = {}) {
    this.coarseStepMs = o.coarseStepMs ?? 1000;
    this.trailMs = o.trailMs ?? 4 * 3600_000;
    this.msgMult = o.msgMult ?? 1;
    this.cadenceMs = o.cadenceMs ?? FINE_STEP_MS;
    this.norm = o.norm ?? "colMax";
    this.mode = o.mode ?? "log";
    this.caps = o.caps ?? FULL_CAPS;
    this.profile = selectProfile(this.caps);
    this.rng = mulberry32(o.seed ?? 1234);
    this.fine = new Ring(FINE_COLS, ROWS, this.cadenceMs);
    this.coarse = new Ring(COARSE_COLS, ROWS, this.coarseStepMs);
    this.lut = buildLut("dark");
    this.mid = ROWS / 2;
    this.priceOrigin = 100000; // integer ticks of logical row 0
    this.vMax = 1000;
    this.coarseAcc = new Uint16Array(ROWS);
    this.coarseElapsed = 0;
    this.book = new Float32Array(ROWS); // signed depth (bid>0, ask<0)
    this.c = {
      columns: 0,
      msgs: 0,
      priceOriginShifts: 0,
      rowsReuploaded: 0,
      lutUploads: 1,
      lutSwapMs: 0,
      contextLosses: 0,
      recoveryBytes: 0,
      shiftBytes: 0,
      shiftFrameMs: 0,
      cpuTickMsMax: 0,
    };
    this.events = []; // {t, bytes} for trailing-1s upload rate
    this._stats = null;
    this._lastUp = 0;
    this.tMs = 0;
    this.forceJumpRows = 0;
    this.pendingCoarseShift = 0;
    this._lastStreamT = -Infinity;
  }

  init() {
    this._regenBook();
    this.preloadTrail(this.trailMs);
  }

  /** History already resident (loaded before measurement; not counted as upload). */
  preloadTrail(trailMs) {
    const col = new Uint16Array(ROWS);
    const coarseCols = Math.min(COARSE_COLS, Math.floor(trailMs / this.coarseStepMs));
    for (let i = 0; i < coarseCols; i += 1)
      this.coarse.writeColumn(
        -(coarseCols - i) * this.coarseStepMs,
        i % 64 === 0 ? this._column(col) : col,
      );
    const fineCols = Math.min(FINE_COLS, Math.floor(trailMs / this.cadenceMs));
    for (let i = 0; i < fineCols; i += 1)
      this.fine.writeColumn(
        -(fineCols - i) * this.cadenceMs,
        i % 64 === 0 ? this._column(col) : col,
      );
    for (const r of [this.fine, this.coarse]) {
      r.uploadedBytes = 0;
      r.ringWraps = 0;
    }
  }

  _regenBook() {
    for (let r = 0; r < ROWS; r += 1) {
      const d = r - this.mid;
      const base = 600 * Math.exp(-Math.abs(d) / 60) * (0.4 + this.rng());
      const wall = this.rng() < 0.004 ? 4000 : 0; // liquidity spike (must survive max-pool)
      this.book[r] = (d < 0 ? 1 : -1) * (base + wall);
    }
  }

  /** Apply n delta messages to the working book (sampled at the visual cadence). */
  _applyMessages(n) {
    for (let k = 0; k < n; k += 1) {
      const r = (this.rng() * ROWS) | 0;
      const d = r - this.mid;
      this.book[r] =
        (d < 0 ? 1 : -1) * Math.max(0, Math.abs(this.book[r]) + (this.rng() - 0.5) * 200);
    }
    this.c.msgs += n;
  }

  /** Quantise working book to signed half-floats (sign bit = ask side). */
  _column(out) {
    let colMax = 0;
    for (let r = 0; r < ROWS; r += 1) colMax = Math.max(colMax, Math.abs(this.book[r]));
    const scale = this.norm === "global" ? this.vMax : Math.max(colMax, 1);
    for (let r = 0; r < ROWS; r += 1) {
      const t = intensity(Math.abs(this.book[r]), scale, this.mode);
      out[r] = toHalf(this.book[r] < 0 ? -t : t);
    }
    return out;
  }

  _record(bytes) {
    this.events.push({ t: this.tMs, bytes });
  }

  /** One visual-refresh tick: coalesce messages, sample, upload ONE column (+coarse on its cadence). */
  _streamTick() {
    this._applyMessages(5 * this.msgMult);
    let up = 0;
    const drift = Math.round(this.mid - ROWS / 2);
    if (this.forceJumpRows || (Math.abs(drift) > 160 && this.pendingCoarseShift === 0)) {
      const n = this.forceJumpRows || drift;
      this.forceJumpRows = 0;
      const t0 = performance.now();
      // Fine ring shifts now; the 14,400-col coarse ring is amortised over later
      // frames (COARSE_SHIFT_ROWS_PER_TICK) so no single frame uploads ~1.3 MB.
      const res = this.fine.shiftRows(n);
      up += res.bytes;
      this.c.rowsReuploaded += res.rows;
      this.c.shiftBytes += res.bytes;
      this.pendingCoarseShift += n;
      this.priceOrigin += n;
      this.mid -= n;
      this.c.priceOriginShifts += 1;
      this._regenBook();
      this.c.shiftFrameMs = performance.now() - t0;
    }
    if (this.pendingCoarseShift !== 0) {
      const sgn = Math.sign(this.pendingCoarseShift);
      const k = Math.min(COARSE_SHIFT_ROWS_PER_TICK, Math.abs(this.pendingCoarseShift));
      const res = this.coarse.shiftRows(sgn * k);
      this.pendingCoarseShift -= sgn * k;
      up += res.bytes;
      this.c.rowsReuploaded += res.rows;
      this.c.shiftBytes += res.bytes;
    }
    const col = new Uint16Array(ROWS);
    this._column(col);
    up += this.fine.writeColumn(this.tMs, col);
    this.c.columns += 1;
    maxMagnitudeInto(this.coarseAcc, col);
    this.coarseElapsed += this.cadenceMs;
    if (this.coarseElapsed >= this.coarseStepMs) {
      up += this.coarse.writeColumn(this.tMs, this.coarseAcc);
      this.coarseAcc.fill(0);
      this.coarseElapsed = 0;
    }
    this._record(up);
    this._lastUp = up;
    this.mid += (this.rng() - 0.5) * 0.8; // random walk (rows)
  }

  /** Theme/convention switch: ONE 256x1 upload, no heatmap data touched. */
  swapConvention() {
    const t0 = performance.now();
    swapHalves(this.lut);
    this.c.lutUploads += 1;
    this._record(this.lut.byteLength);
    this.c.lutSwapMs = performance.now() - t0;
    return { uploads: 1, bytes: this.lut.byteLength, ms: this.c.lutSwapMs };
  }

  /** WebGL context loss: GPU copies invalidated; rebuild from the CPU data model. */
  loseContext() {
    this.c.contextLosses += 1;
    const t0 = performance.now();
    const bytes = this.fine.bytes + this.coarse.bytes + this.lut.byteLength;
    // Re-upload from this.fine/this.coarse (CPU data model untouched => no data loss).
    this.c.recoveryBytes += bytes;
    this._record(bytes);
    return { bytes, ms: performance.now() - t0, fineColumnsIntact: this.fine.count };
  }

  step(tMs, input) {
    if (tMs < this.tMs) {
      this.events.length = 0;
      this._lastStreamT = -Infinity;
    } // new repetition: restart the 1 s window
    this.tMs = tMs;
    this._lastUp = 0;
    const t0 = performance.now();
    if (
      input &&
      input.kind === "heatmapStream" &&
      tMs - this._lastStreamT >= this.cadenceMs - 1 // degradation lever: sample slower than the driver
    ) {
      this._lastStreamT = tMs;
      this._streamTick();
    }
    const cpuMs = performance.now() - t0;
    if (cpuMs > this.c.cpuTickMsMax) this.c.cpuTickMsMax = cpuMs;
    while (this.events.length && this.events[0].t < tMs - 1000) this.events.shift();
    const bytesPerSec = this.events.reduce((a, e) => a + e.bytes, 0);
    const quads = this.fine.drawRanges().length + this.coarse.drawRanges().length;
    const stage = {
      inputHandling: 0.05,
      // Modelled from counted work (rows quantised) so per-rep JIT noise cannot break the
      // harness's stage-attribution check; wall-clock CPU is reported as cpuTickMsMax.
      dataWindowRecompute: this._lastUp > 0 ? 0.05 + (this._lastUp / 1024) * 0.02 : 0,
      candleGeometry: 0,
      footprintTextGeometry: 0,
      heatmapUpload: (this._lastUp / 1024) * GPU_UPLOAD_PER_KB,
      paneRedraw: BASE_OTHER_MS * 0.6 + quads * GPU_QUAD,
      overlayRedraw: 0,
      domMirrorSync: 0,
      compositePresent: BASE_OTHER_MS * 0.4,
    };
    this._stats = {
      frameTimeMs: Object.values(stage).reduce((a, b) => a + b, 0),
      drawCalls: quads + 1,
      uploadedBytesPerSec: bytesPerSec,
      textureMemMB: (this.fine.bytes + this.coarse.bytes + this.lut.byteLength) / 1048576,
      perStageMs: stage,
    };
  }

  /** Intensity accessor at (col,row) for the a11y mirror (E06-D03). */
  intensityAt(col, logicalRow) {
    const h = this.fine.texel(col, logicalRow);
    return { raw: h, side: h & 0x8000 ? "ask" : "bid" };
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

  extendedStats() {
    return {
      columnsPerSec: 1000 / this.cadenceMs,
      ...this.c,
      profile: this.profile,
      fineRingBytes: this.fine.bytes,
      coarseRingBytes: this.coarse.bytes,
      ringWraps: this.fine.ringWraps,
      coarseRingWraps: this.coarse.ringWraps,
      uploadedBytesPerSec: this.stats().uploadedBytesPerSec,
      logK: LOG_K,
    };
  }

  dispose() {
    this.events = [];
  }
}
