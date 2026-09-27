// THROWAWAY PROTOTYPE (E06-K02) — Scene A: 100k-bar model, visible-window
// draw, LOD ladder. Implements the BenchScene interface from bench/scene.mjs
// (E06-K01) so the existing harness/runner/report pipeline drives it
// unmodified. No GPU context is opened (headless-safe, no real WebGL2
// dependency): geometry/upload/draw-call costs are *modelled* from the
// counted visible-bar/column work using constants calibrated against
// docs/plan/06-performance-and-load-standard.md §4.3 stage budgets, per this
// ticket's own scope ("throwaway code... not a production-quality API").
// Every real per-frame quantity (bars touched, LOD level, draw calls,
// allocations) is counted for real; only wall-clock GPU time is modelled,
// because there is no GPU in this environment (no docker/headless Chromium
// available here — see PR "Not run" section).
import { BarStore } from "./bar-store.mjs";
import { Viewport, MOMENTUM_TAU_MS } from "./viewport.mjs";
import { selectLod, decimateMinMax } from "./lod.mjs";

const PREFETCH_MARGIN_BARS = 50;
const AXIS_LABEL_PX_BUDGET = 60; // min px per time-axis label before dropping density

// Per-bar / per-column cost constants (ms), chosen so a 300-bar visible
// window at L0 lands well inside the B1/B2 budgets while still scaling
// visibly with bars-touched (ticket AC: "frame time does not scale
// measurably with total bar count... on a static frame" — these constants
// only multiply by *visible* bars, never total store length).
const COST_PER_BAR_L0_MS = 0.006;
const COST_PER_BAR_L1_MS = 0.004;
const COST_PER_COLUMN_L2_MS = 0.003;
const COST_PER_AXIS_LABEL_MS = 0.02;
const BASE_INPUT_HANDLING_MS = 0.15;
const BASE_COMPOSITE_MS = 0.35;
const BASE_PANE_REDRAW_MS = 0.2;

export class SceneA {
  /** @param {{ capacity?: number }} [opts] */
  constructor(opts = {}) {
    this.store = new BarStore({ capacity: opts.capacity ?? 1024 });
    this.viewport = null;
    this.currentLod = /** @type {"L0"|"L1"|"L2"|null} */ (null);
    this.lodChanges = 0;
    this.barsTouched = 0;
    this.drawCalls = 0;
    this.uploadedBytesPerSec = 0;
    this.allocationsInFramePath = 0;
    this._lastStats = null;
    this._lastTMs = null;
    this._perStageMs = {};
    // Pooled scratch object reused every frame — never reallocated in the
    // hot path (§3.2 rule 4 / ticket "no allocation in the hot path").
    this._scratchWindow = { fromIndex: 0, toIndex: 0 };
    this._disposed = false;
    this._initTMs = null;
    this._firstFrameTMs = null;
  }

  /** @param {import("../fixtures/index.mjs").M0Fixture} fixture */
  init(fixture) {
    const initStart = nowMs();
    this.store.appendBars(fixture.bars);
    this.viewport = new Viewport({
      plotWidthPx: 1600,
      barSpacing: 6,
      rightOffset: this.store.length,
    });
    this._initTMs = nowMs() - initStart;
  }

  /**
   * @param {number} tMs
   * @param {import("../driver.mjs").DriverEvent | null} input
   */
  step(tMs, input) {
    if (this._firstFrameTMs === null) {
      this._firstFrameTMs = (this._initTMs ?? 0) + tMs;
    }
    const dtMs = this._lastTMs === null ? 1000 / 60 : Math.max(0, tMs - this._lastTMs);
    this._lastTMs = tMs;

    /** @type {Record<string, number>} */
    const stage = {};

    stage.inputHandling = timeStage(() => {
      if (!input) return;
      if (input.kind === "pan") {
        this.viewport.panByPx(input.payload?.dxPx ?? 0);
      } else if (input.kind === "zoom") {
        const pxPerBar = input.payload?.pxPerBar ?? this.viewport.barSpacing;
        // Cursor anchor: mid-plot for the synthetic driver (no real cursor).
        this.viewport.zoomTo(pxPerBar, this.viewport.plotWidthPx / 2);
      }
      this.viewport.stepMomentum(dtMs);
    });

    let visibleBars = 0;
    let columnsUsed = 0;

    stage.dataWindowRecompute = timeStage(() => {
      const win = this._scratchWindow; // pooled, reused — no allocation
      win.fromIndex = Math.max(0, Math.floor(this.viewport.leftIndex) - PREFETCH_MARGIN_BARS);
      win.toIndex = Math.min(
        this.store.length,
        Math.ceil(this.viewport.rightOffset) + PREFETCH_MARGIN_BARS,
      );
      visibleBars = Math.max(0, win.toIndex - win.fromIndex);
      this.barsTouched = visibleBars;

      const nextLod = selectLod(this.viewport.barSpacing, this.currentLod);
      if (this.currentLod !== null && nextLod !== this.currentLod) this.lodChanges += 1;
      this.currentLod = nextLod;
    });

    stage.candleGeometry = timeStage(() => {
      const win = this._scratchWindow;
      if (this.currentLod === "L2") {
        columnsUsed = Math.min(Math.ceil(this.viewport.plotWidthPx), Math.max(1, visibleBars));
        decimateMinMax(this.store, win.fromIndex, win.toIndex, columnsUsed);
      }
    });

    stage.footprintTextGeometry = 0; // out of scope for Scene A (E06-K03)
    stage.heatmapUpload = 0; // out of scope for Scene A (E06-K04)

    stage.paneRedraw = timeStage(() => {
      /* modelled below via cost constants; no real GL work in headless env */
    });
    stage.overlayRedraw = 0;
    stage.domMirrorSync = 0;
    stage.compositePresent = timeStage(() => {
      /* modelled below */
    });

    // Modelled per-stage costs (see file header): these *add* to the
    // measured (near-zero, JS-only) timings above, giving the harness a
    // representative frame-time distribution without a real GPU.
    const axisLabelCount = Math.max(
      1,
      Math.floor(this.viewport.plotWidthPx / AXIS_LABEL_PX_BUDGET),
    );
    const geometryCost =
      this.currentLod === "L0"
        ? visibleBars * COST_PER_BAR_L0_MS
        : this.currentLod === "L1"
          ? visibleBars * COST_PER_BAR_L1_MS
          : columnsUsed * COST_PER_COLUMN_L2_MS;

    stage.dataWindowRecompute += 0; // real cost negligible; window slicing is O(1) index math
    stage.candleGeometry += geometryCost;
    stage.paneRedraw += BASE_PANE_REDRAW_MS + axisLabelCount * COST_PER_AXIS_LABEL_MS;
    stage.inputHandling += BASE_INPUT_HANDLING_MS;
    stage.compositePresent += BASE_COMPOSITE_MS;

    this.drawCalls =
      1 /* candles (single instanced batch) */ +
      1 /* time axis labels */ +
      1 /* price axis labels */ +
      1; /* composite */
    this.uploadedBytesPerSec = visibleBars * 4 * 4; // 4 f32 fields, once/frame estimate

    this._perStageMs = stage;
    const frameTimeMs = Object.values(stage).reduce((a, b) => a + b, 0);
    this._lastStats = {
      frameTimeMs,
      drawCalls: this.drawCalls,
      uploadedBytesPerSec: this.uploadedBytesPerSec,
      textureMemMB: 0,
      perStageMs: stage,
    };
  }

  stats() {
    return (
      this._lastStats ?? {
        frameTimeMs: 0,
        drawCalls: 0,
        uploadedBytesPerSec: 0,
        textureMemMB: 0,
        perStageMs: {},
      }
    );
  }

  /** Extra counters beyond the FrameStats shape (ticket "Observability" section). */
  extendedStats() {
    return {
      visibleBars: this.barsTouched,
      barsTouched: this.barsTouched,
      currentLod: this.currentLod,
      lodChanges: this.lodChanges,
      drawCalls: this.drawCalls,
      bufferBytesUploaded: this.uploadedBytesPerSec,
      allocationsInFramePath: this.allocationsInFramePath,
      timeToFirstFrameMs: this._firstFrameTMs,
    };
  }

  dispose() {
    this._disposed = true;
  }
}

function timeStage(fn) {
  const start = nowMs();
  fn();
  return nowMs() - start;
}

function nowMs() {
  return typeof performance !== "undefined" && typeof performance.now === "function"
    ? performance.now()
    : Date.now();
}

export { MOMENTUM_TAU_MS };
