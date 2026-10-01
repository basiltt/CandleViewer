// THROWAWAY PROTOTYPE (E06-K03). Two-pass Felzenszwalb-Huttenlocher EDT and
// 8-bit single-channel SDF generation (docs/plan/26-chart-engine-design.md §3.7).
export const INF = 1e20;

/**
 * 1D squared-distance transform (Felzenszwalb & Huttenlocher).
 * @param {Float64Array} f input cost per sample
 * @param {number} n
 * @param {Float64Array} out
 * @param {Int32Array} v scratch (n)
 * @param {Float64Array} z scratch (n+1)
 */
export function edt1d(f, n, out, v, z) {
  let k = 0;
  v[0] = 0;
  z[0] = -INF;
  z[1] = INF;
  for (let q = 1; q < n; q += 1) {
    let s = (f[q] + q * q - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]);
    while (s <= z[k]) {
      k -= 1;
      s = (f[q] + q * q - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]);
    }
    k += 1;
    v[k] = q;
    z[k] = s;
    z[k + 1] = INF;
  }
  k = 0;
  for (let q = 0; q < n; q += 1) {
    while (z[k + 1] < q) k += 1;
    const d = q - v[k];
    out[q] = d * d + f[v[k]];
  }
}

/**
 * 2D squared EDT in place: distance^2 to the nearest cell where grid === 0.
 * @param {Float64Array} grid w*h; 0 for feature, INF otherwise.
 */
export function edt2d(grid, w, h) {
  const m = Math.max(w, h);
  const f = new Float64Array(m);
  const out = new Float64Array(m);
  const v = new Int32Array(m);
  const z = new Float64Array(m + 1);
  for (let x = 0; x < w; x += 1) {
    for (let y = 0; y < h; y += 1) f[y] = grid[y * w + x];
    edt1d(f, h, out, v, z);
    for (let y = 0; y < h; y += 1) grid[y * w + x] = out[y];
  }
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) f[x] = grid[y * w + x];
    edt1d(f, w, out, v, z);
    for (let x = 0; x < w; x += 1) grid[y * w + x] = out[x];
  }
}

/**
 * Coverage bitmap (>=128 inside) -> 8-bit SDF; 128 is the edge, `spread` px
 * maps to the full range (inside > 128).
 * @param {Uint8Array} bitmap
 */
export function bitmapToSdf(bitmap, w, h, spread = 4) {
  const toInside = new Float64Array(w * h);
  const toOutside = new Float64Array(w * h);
  for (let i = 0; i < w * h; i += 1) {
    const inside = bitmap[i] >= 128;
    toInside[i] = inside ? 0 : INF;
    toOutside[i] = inside ? INF : 0;
  }
  edt2d(toInside, w, h);
  edt2d(toOutside, w, h);
  const sdf = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i += 1) {
    const signedOutside = Math.sqrt(toInside[i]) - Math.sqrt(toOutside[i]);
    const norm = 0.5 - signedOutside / (2 * spread);
    sdf[i] = Math.max(0, Math.min(255, Math.round(norm * 255)));
  }
  return sdf;
}
