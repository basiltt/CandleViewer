// THROWAWAY PROTOTYPE (E06-K03) — Scene B: SDF text atlas + 2,500-cell
// footprint density (B3). Implements the E06-K01 BenchScene contract.
// No GPU in this environment: CPU-side work (formatting, glyph-run build,
// instance packing, LOD, store ops) is MEASURED for real; GPU/fill cost is
// MODELLED from counted glyphs/draw calls (constants below, calibrated to
// 06-performance-and-load-standard.md §4.3 and 26-…§3.7's 0.4 ms GPU figure).
// The Canvas-2D arm is a spot-check model only (ticket "Scope trim").
import { FootprintStore } from "./footprint-store.mjs";
import { GlyphRunCache, FLOATS_PER_GLYPH } from "./glyph-runs.mjs";
import { generateAtlas } from "./atlas.mjs";
import { selectFootprintLod, numbersAtLod, formatVolume, formatDelta } from "./footprint-lod.mjs";

export const VISIBLE_CELLS_TARGET = 2500;
const MAX_GLYPHS_PER_DRAW = 1 << 16; // instance budget per text draw call
// Modelled GPU costs (ms).
const GPU_SDF_PER_GLYPH = 0.00003;
const GPU_OUTLINE_PER_GLYPH = 0.000012; // second smoothstep threshold
const GPU_HATCH_PER_DOUBLE_FLAG_CELL = 0.0004;
const GPU_CELL_QUAD_PER_CELL = 0.00008;
// Canvas-2D glyph cache arm: one drawImage per glyph (cannot batch), plus
// per-call JS->raster overhead. Assumed, not measured here (see findings).
const C2D_PER_GLYPH = 0.0011;
const BASE_OTHER_MS = 0.9;

const FILL = [0.91, 0.92, 0.93, 1];

export class SceneB {
  /**
   * @param {{arm?: "sdf"|"canvas2d", cells?: number, outline?: boolean,
   *   cellHeightPx?: number, format?: "full"|"compact", atlas?: object}} [opts]
   */
  constructor(opts = {}) {
    this.arm = opts.arm ?? "sdf";
    this.cellTarget = opts.cells ?? VISIBLE_CELLS_TARGET;
    this.outline = opts.outline ?? true;
    this.cellHeightPx = opts.cellHeightPx ?? 14;
    this.format = opts.format ?? "full";
    this.volumeScale = opts.volumeScale ?? 1.5; // ~5-6 chars/number-pair; 60 = 5-digit stress
    this.store = new FootprintStore();
    this.atlas = opts.atlas ?? null;
    this.runs = null;
    this.lod = null;
    this.lodChanges = 0;
    this.visible = { from: 0, to: 0 };
    this._stats = null;
    this._counters = {};
    this._lastRebuildMs = 0;
    this._firstFrameTMs = null;
    this._lastTMs = null;
  }

  init(fixture) {
    const t0 = performance.now();
    if (!this.atlas) this.atlas = generateAtlas();
    this.atlasGenMs = this.atlas.genMs ?? 0;
    this.runs = new GlyphRunCache(this.atlas.glyphs);
    // Synthetic cells: take the first N cells of the K01 fixture, if present.
    const src = fixture?.footprintCells ?? [];
    const cells = [];
    for (let i = 0; i < Math.min(this.cellTarget, src.length || this.cellTarget); i += 1) {
      const c = src[i] ?? {
        barIndex: (i / 25) | 0,
        priceTicks: i % 25,
        bid: (i * 37) % 9000,
        ask: (i * 91) % 12000,
        tradeCount: i % 40,
      };
      const imbalanced = i % 11 === 0;
      const estimated = i % 13 === 0;
      cells.push({
        barIndex: c.barIndex,
        priceLevel: c.priceTicks,
        bidVol: c.bid * this.volumeScale,
        askVol: c.ask * this.volumeScale,
        tradeCount: c.tradeCount,
        flags: (imbalanced ? 1 : 0) | (estimated ? 2 : 0),
      });
    }
    this.store.upsertFootprintCells(cells);
    this.visible = { from: 0, to: this.store.length };
    this._rebuildRuns();
    this.initMs = performance.now() - t0;
  }

  /** Re-formats and re-lays-out every visible cell's run (data untouched). */
  _rebuildRuns() {
    const t0 = performance.now();
    const lod = selectFootprintLod(this.cellHeightPx, this.lod);
    if (this.lod !== null && lod !== this.lod) this.lodChanges += 1;
    this.lod = lod;
    this.runs.invalidateFormat();
    const n = numbersAtLod(lod);
    if (n > 0) {
      const h = Math.min(this.cellHeightPx - 2, 12);
      for (let i = this.visible.from; i < this.visible.to; i += 1) {
        const bid = this.store.bidVol[i];
        const ask = this.store.askVol[i];
        const text =
          n === 2
            ? `${formatVolume(bid, this.format)} ${formatVolume(ask, this.format)}`
            : formatDelta(ask - bid, this.format);
        this.runs.append(i, text, (i % 50) * 44, ((i / 50) | 0) * this.cellHeightPx, h, FILL);
      }
    }
    this._lastRebuildMs = performance.now() - t0;
    return this._lastRebuildMs;
  }

  /** Switch number format: only the glyph-run cache is invalidated. */
  setFormat(mode) {
    this.format = mode;
    return this._rebuildRuns();
  }

  setCellHeight(px) {
    this.cellHeightPx = px;
    return this._rebuildRuns();
  }

  step(tMs, input) {
    if (this._firstFrameTMs === null) this._firstFrameTMs = tMs;
    /** @type {Record<string, number>} */
    const stage = {};
    const t0 = performance.now();
    if (input && input.kind === "footprintHold" && input.payload?.rebuild) {
      this._rebuildRuns();
    }
    stage.dataWindowRecompute = performance.now() - t0;
    // Measured CPU text batching: walk the pooled instance array once, as the
    // upload would (checksum prevents dead-code elimination).
    const tb = performance.now();
    const glyphCount = this.runs.glyphCount;
    const inst = this.runs.instances;
    let sum = 0;
    for (let i = 0; i < glyphCount * FLOATS_PER_GLYPH; i += FLOATS_PER_GLYPH) sum += inst[i + 4];
    this._checksum = sum;
    const cpuBatchMs = performance.now() - tb;

    const cells = this.visible.to - this.visible.from;
    const textDrawCalls =
      glyphCount === 0
        ? 0
        : this.arm === "sdf"
          ? Math.ceil(glyphCount / MAX_GLYPHS_PER_DRAW)
          : glyphCount;
    let doubleFlag = 0;
    for (let i = this.visible.from; i < this.visible.to; i += 1)
      if (this.store.flags[i] === 3) doubleFlag += 1;

    let outlinePassMs = 0;
    let textStageMs;
    if (this.arm === "sdf") {
      outlinePassMs = this.outline ? glyphCount * GPU_OUTLINE_PER_GLYPH : 0;
      textStageMs = cpuBatchMs + glyphCount * GPU_SDF_PER_GLYPH + outlinePassMs;
    } else {
      textStageMs = cpuBatchMs + glyphCount * C2D_PER_GLYPH;
      outlinePassMs = this.outline ? glyphCount * C2D_PER_GLYPH * 0.9 : 0; // second drawImage (stroke) per glyph
      textStageMs += outlinePassMs;
    }
    stage.footprintTextGeometry =
      textStageMs + cells * GPU_CELL_QUAD_PER_CELL + doubleFlag * GPU_HATCH_PER_DOUBLE_FLAG_CELL;
    stage.paneRedraw = BASE_OTHER_MS * 0.6;
    stage.compositePresent = BASE_OTHER_MS * 0.4;
    stage.inputHandling = 0.05;
    stage.candleGeometry = 0;
    stage.heatmapUpload = 0;
    stage.overlayRedraw = 0;
    stage.domMirrorSync = 0;

    const frameTimeMs = Object.values(stage).reduce((a, b) => a + b, 0);
    const textureMemMB =
      this.arm === "sdf" ? (this.atlas.size * this.atlas.size) / (1024 * 1024) : 2;
    this._counters = {
      visibleCells: cells,
      glyphCount,
      textDrawCalls,
      textBatchMs: textStageMs - outlinePassMs,
      outlinePassMs,
      atlasGenMs: this.atlasGenMs,
      atlasCacheHit: this.atlasCacheHit ?? false,
      atlasTextureBytes: this.atlas.size * this.atlas.size,
      lod: this.lod,
      doubleFlagCells: doubleFlag,
    };
    this._stats = {
      frameTimeMs,
      drawCalls: 1 /* cell quads */ + textDrawCalls + 1 /* composite */,
      uploadedBytesPerSec: 0,
      textureMemMB,
      perStageMs: stage,
    };
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
    return { ...this._counters, lodChanges: this.lodChanges, lastRebuildMs: this._lastRebuildMs };
  }

  dispose() {
    this.runs = null;
  }
}
