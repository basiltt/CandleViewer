// THROWAWAY PROTOTYPE (E06-K03). Per-cell glyph-run cache. Runs are strings
// laid out into a pooled instance Float32Array (12 floats/glyph: posPx.xy,
// sizePx.xy, uvRect.xyzw, colour.rgba). Built on data update, one append per cell;
// a format change invalidates only this cache, never the cell data.
export const FLOATS_PER_GLYPH = 12;

export class GlyphRunCache {
  /** @param {Record<string, any>} glyphs atlas glyph table */
  constructor(glyphs, capacityGlyphs = 1 << 16) {
    this.glyphs = glyphs;
    this.instances = new Float32Array(capacityGlyphs * FLOATS_PER_GLYPH);
    this.glyphCount = 0;
    /** cellIndex -> {start,count,fmtVersion} (start in glyphs) */
    this.runs = new Map();
    this.formatVersion = 0;
    this.invalidations = 0;
    this.rebuilds = 0;
  }

  /** Format change: drop runs only. Cell data stays untouched. */
  invalidateFormat() {
    this.formatVersion += 1;
    this.runs.clear();
    this.glyphCount = 0;
    this.invalidations += 1;
  }

  has(cellIndex) {
    return this.runs.has(cellIndex);
  }

  /**
   * Lays out `text` with cell-local origin (x,y) and glyph height `hPx`.
   * @returns {{start:number,count:number}}
   */
  append(cellIndex, text, x, y, hPx, rgba) {
    const start = this.glyphCount;
    const scale = hPx / 24;
    let pen = x;
    for (const ch of text) {
      const g = this.glyphs[ch];
      if (!g) continue;
      if ((this.glyphCount + 1) * FLOATS_PER_GLYPH > this.instances.length) this._grow();
      const o = this.glyphCount * FLOATS_PER_GLYPH;
      const a = this.instances;
      a[o] = pen;
      a[o + 1] = y;
      a[o + 2] = g.w * scale;
      a[o + 3] = g.h * scale;
      a[o + 4] = g.u0;
      a[o + 5] = g.v0;
      a[o + 6] = g.u1;
      a[o + 7] = g.v1;
      a[o + 8] = rgba[0];
      a[o + 9] = rgba[1];
      a[o + 10] = rgba[2];
      a[o + 11] = rgba[3];
      pen += g.advance * scale;
      this.glyphCount += 1;
    }
    const run = { start, count: this.glyphCount - start, fmtVersion: this.formatVersion };
    this.runs.set(cellIndex, run);
    this.rebuilds += 1;
    return run;
  }

  _grow() {
    const next = new Float32Array(this.instances.length * 2);
    next.set(this.instances);
    this.instances = next;
  }
}
