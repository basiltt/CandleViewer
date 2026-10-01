// THROWAWAY PROTOTYPE (E06-K03). SDF atlas pipeline: frozen glyph set
// (docs/design/E06/E06-D01.md §3), deterministic shelf packer, generation,
// and a cache keyed by (fontFamily, weight, hash(glyphSet)) with a pluggable
// store (IndexedDB in a browser, in-memory here).
import { bitmapToSdf } from "./edt.mjs";

export const ATLAS_SIZE = 1024;
export const GLYPH_PX = 24; // single SDF size-class; scaled in the shader
export const SDF_SPREAD = 4;
export const GLYPH_SET =
  "0123456789.,-+%×KMB" +
  "ABCDEFGHIJKLMNOPQRSTUVWXYZ" +
  "abcdefghijklmnopqrstuvwxyz" +
  "▲▼" +
  " ()";

export function fnv1a(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i += 1) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}

export const glyphSetHash = (set = GLYPH_SET) => fnv1a(set);
export const atlasCacheKey = (fontFamily, weight, set = GLYPH_SET) =>
  `${fontFamily}|${weight}|${glyphSetHash(set)}`;

/**
 * Deterministic shelf packer: sorted by (height desc, codepoint asc).
 * @param {{ch:string,w:number,h:number}[]} items
 */
export function shelfPack(items, size = ATLAS_SIZE, pad = 1) {
  const sorted = [...items].sort((a, b) => b.h - a.h || a.ch.codePointAt(0) - b.ch.codePointAt(0));
  /** @type {Map<string,{x:number,y:number,w:number,h:number}>} */
  const placements = new Map();
  let x = 0;
  let y = 0;
  let shelfH = 0;
  for (const it of sorted) {
    if (x + it.w + pad > size) {
      y += shelfH + pad;
      x = 0;
      shelfH = 0;
    }
    if (y + it.h + pad > size) throw new Error("[atlas] glyph set does not fit atlas");
    placements.set(it.ch, { x, y, w: it.w, h: it.h });
    x += it.w + pad;
    shelfH = Math.max(shelfH, it.h);
  }
  const orderHash = fnv1a(sorted.map((s) => s.ch).join(""));
  return { placements, orderHash, usedHeight: y + shelfH };
}

/**
 * Procedural stand-in rasteriser (no 2D canvas in Node). A browser run swaps
 * in an OffscreenCanvas fillText rasteriser with the same signature. EDT and
 * packing cost is real; glyph shape fidelity is not a goal.
 */
export function proceduralRasterizer(ch, px = GLYPH_PX) {
  const w = Math.round(px * 0.6) + SDF_SPREAD * 2;
  const h = px + SDF_SPREAD * 2;
  const bitmap = new Uint8Array(w * h);
  const cp = ch.codePointAt(0);
  const iw = w - SDF_SPREAD * 2;
  for (let ly = 0; ly < px; ly += 1) {
    for (let lx = 0; lx < iw; lx += 1) {
      const stem = lx < 3 || lx >= iw - 3;
      const bar = ly < 3 || ly >= px - 3 || Math.abs(ly - px / 2) < 1.5;
      const on =
        (stem && ((cp >> (ly % 7)) & 1) === 1) ||
        (bar && ((cp >> (lx % 5)) & 1) === 1) ||
        lx === ly % iw;
      if (on) bitmap[(ly + SDF_SPREAD) * w + lx + SDF_SPREAD] = 255;
    }
  }
  return { w, h, advance: w - SDF_SPREAD, bitmap };
}

/** @param {{rasterize?: Function, glyphSet?: string, size?: number}} [opts] */
export function generateAtlas(opts = {}) {
  const { rasterize = proceduralRasterizer, glyphSet = GLYPH_SET, size = ATLAS_SIZE } = opts;
  const t0 = performance.now();
  const rasters = [...glyphSet].map((ch) => ({ ch, ...rasterize(ch) }));
  const { placements, orderHash, usedHeight } = shelfPack(rasters, size);
  const texture = new Uint8Array(size * size);
  /** @type {Record<string, {u0:number,v0:number,u1:number,v1:number,w:number,h:number,advance:number}>} */
  const glyphs = {};
  for (const r of rasters) {
    const p = placements.get(r.ch);
    const sdf = bitmapToSdf(r.bitmap, r.w, r.h, SDF_SPREAD);
    for (let y = 0; y < r.h; y += 1) {
      texture.set(sdf.subarray(y * r.w, (y + 1) * r.w), (p.y + y) * size + p.x);
    }
    glyphs[r.ch] = {
      u0: p.x / size,
      v0: p.y / size,
      u1: (p.x + r.w) / size,
      v1: (p.y + r.h) / size,
      w: r.w,
      h: r.h,
      advance: r.advance,
    };
  }
  return { size, texture, glyphs, orderHash, usedHeight, genMs: performance.now() - t0 };
}

/** In-memory stand-in for IndexedDB (same async get/put shape). */
export class MemoryAtlasStore {
  constructor() {
    this.m = new Map();
  }
  async get(key) {
    return this.m.get(key) ?? null;
  }
  async put(key, value) {
    this.m.set(key, value);
  }
}

/**
 * Cache-aware load. Stored value = glyph bitmaps + table keyed by a font
 * hash only: no user data, nothing user-identifying in the key.
 */
export async function loadAtlas(store, fontFamily, weight, opts = {}) {
  const key = atlasCacheKey(fontFamily, weight, opts.glyphSet);
  const t0 = performance.now();
  const hit = await store.get(key);
  if (hit) return { atlas: { ...hit, genMs: 0 }, cacheHit: true, ms: performance.now() - t0 };
  const atlas = generateAtlas(opts);
  await store.put(key, {
    size: atlas.size,
    texture: atlas.texture,
    glyphs: atlas.glyphs,
    orderHash: atlas.orderHash,
    usedHeight: atlas.usedHeight,
  });
  return { atlas, cacheHit: false, ms: performance.now() - t0 };
}

/** WCAG relative luminance contrast ratio for #RRGGBB strings. */
export function contrastRatio(fg, bg) {
  const lum = (hex) => {
    const c = [1, 3, 5]
      .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}
