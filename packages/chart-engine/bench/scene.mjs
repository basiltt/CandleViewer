// BenchScene interface (E06-K01 ticket "Technical notes / design" bullet).
// Kept deliberately minimal so K02/K03/K04's prototype scenes are swappable
// without touching the harness. No production engine code lives here —
// only the contract and a stub scene used by this ticket's own tests/CLI
// smoke run (out of scope: "Any production engine code").

/**
 * @typedef {{ frameTimeMs: number, drawCalls: number, uploadedBytesPerSec: number, textureMemMB: number, perStageMs: Record<string, number> }} FrameStats
 */

/**
 * @typedef {{
 *   init(fixture: import("./fixtures/index.mjs").M0Fixture): void | Promise<void>,
 *   step(tMs: number, input: import("./driver.mjs").DriverEvent | null): void,
 *   stats(): FrameStats,
 *   dispose(): void,
 * }} BenchScene
 */

/**
 * A deterministic stub scene producing a known synthetic frame-time
 * distribution, used to validate the harness's *statistics* (not real GPU
 * performance) per the ticket's Test plan "Integration" bullet.
 * @implements {BenchScene}
 */
export class StubScene {
  /** @param {{ baseMs?: number, jitterMs?: number, seedRng?: () => number }} [opts] */
  constructor(opts = {}) {
    this.baseMs = opts.baseMs ?? 8;
    this.jitterMs = opts.jitterMs ?? 2;
    this.rng = opts.seedRng ?? Math.random;
    this.lastFrameMs = this.baseMs;
    this.disposed = false;
  }

  init() {
    // Interface conformance only — the stub scene ignores the fixture.
  }

  step() {
    this.lastFrameMs = this.baseMs + (this.rng() - 0.5) * 2 * this.jitterMs;
  }

  stats() {
    return {
      frameTimeMs: this.lastFrameMs,
      drawCalls: 12,
      uploadedBytesPerSec: 1024,
      textureMemMB: 4,
      perStageMs: {
        inputHandling: this.lastFrameMs * 0.05,
        dataWindowRecompute: this.lastFrameMs * 0.1,
        candleGeometry: this.lastFrameMs * 0.15,
        footprintTextGeometry: this.lastFrameMs * 0.25,
        heatmapUpload: this.lastFrameMs * 0.15,
        paneRedraw: this.lastFrameMs * 0.1,
        overlayRedraw: this.lastFrameMs * 0.05,
        domMirrorSync: this.lastFrameMs * 0.05,
        compositePresent: this.lastFrameMs * 0.1,
      },
    };
  }

  dispose() {
    this.disposed = true;
  }
}
