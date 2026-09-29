// Stage instrumentation (E06-K01 ticket "Instrumentation" bullet).
// Wraps `Performance.mark()`/`measure()` at each §4.3 stage boundary,
// exported as structured spans (docs/plan/06-performance-and-load-standard.md §7.2).
// No GPU/DOM dependency: works against any `Performance`-shaped object,
// including Node's built-in `perf_hooks.performance` in headless runs.

/** The nine frame-budget stages named in §4.3, in report order. */
export const FRAME_STAGES = /** @type {const} */ ([
  "inputHandling",
  "dataWindowRecompute",
  "candleGeometry",
  "footprintTextGeometry",
  "heatmapUpload",
  "paneRedraw",
  "overlayRedraw",
  "domMirrorSync",
  "compositePresent",
]);

/**
 * Records per-stage durations for one frame using `performance.mark`/`measure`.
 * Instrumentation can be disabled (perturbation-check acceptance criterion)
 * by constructing with `{ enabled: false }`, in which case stage timings are
 * measured with a cheaper `Date.now()`-only path and marks are skipped.
 */
export class FrameInstrumentation {
  /**
   * @param {{ performance: { now(): number, mark?(name: string): void, measure?(name: string, start: string, end: string): void }, enabled?: boolean }} opts
   */
  constructor(opts) {
    this.performance = opts.performance;
    this.enabled = opts.enabled ?? true;
    /** @type {Record<string, number>} */
    this.stageTotals = Object.fromEntries(FRAME_STAGES.map((s) => [s, 0]));
    this.frameCount = 0;
  }

  /**
   * Times a stage's synchronous work and accumulates it into the running
   * per-stage total. Returns the callback's return value unchanged.
   * @template T
   * @param {(typeof FRAME_STAGES)[number]} stage
   * @param {() => T} fn
   * @returns {T}
   */
  timeStage(stage, fn) {
    const startMark = `${stage}-start`;
    const endMark = `${stage}-end`;
    if (this.enabled && this.performance.mark) {
      this.performance.mark(startMark);
    }
    const t0 = this.performance.now();
    const result = fn();
    const t1 = this.performance.now();
    if (this.enabled && this.performance.mark && this.performance.measure) {
      this.performance.mark(endMark);
      this.performance.measure(stage, startMark, endMark);
    }
    this.stageTotals[stage] += t1 - t0;
    return result;
  }

  /** Call once per completed frame to advance the frame counter. */
  endFrame() {
    this.frameCount += 1;
  }

  /**
   * Returns the mean per-stage cost in ms over all frames recorded so far,
   * keyed by stage name (report's `perStageMs` shape).
   * @returns {Record<string, number>}
   */
  perStageMeans() {
    const frames = Math.max(1, this.frameCount);
    /** @type {Record<string, number>} */
    const out = {};
    for (const stage of FRAME_STAGES) {
      out[stage] = this.stageTotals[stage] / frames;
    }
    return out;
  }
}
