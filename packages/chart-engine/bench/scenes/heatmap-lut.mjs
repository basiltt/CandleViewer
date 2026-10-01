// THROWAWAY PROTOTYPE (E06-K04) - 256x1 LUT generated per E06-D02 §3.2 verbatim
// (Oklab interpolation of 5 token stops per side), intensity mapping §3.3 and
// age-decay §3.4. Tokens are read from packages/ui/tokens (no invented palette).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const tokDir = join(dirname(fileURLToPath(import.meta.url)), "../../../ui/tokens");
const load = (f) => JSON.parse(readFileSync(join(tokDir, f), "utf8"));

/** Resolve a (possibly aliased) token name to "#RRGGBB" within a theme. */
export function resolveToken(name, theme = "dark") {
  const prim = load("primitives.tokens.json");
  const sem = load(`semantic-${theme}.tokens.json`);
  let v = (sem[name] ?? prim[name])?.$value;
  for (let i = 0; i < 8 && typeof v === "string" && v.startsWith("{"); i += 1) {
    const k = v.slice(1, -1);
    v = (sem[k] ?? prim[k])?.$value;
  }
  if (typeof v !== "string" || !v.startsWith("#")) throw new Error(`unresolved token ${name}`);
  return v;
}

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
const lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const gam = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);

export function srgbToOklab(h) {
  const [r, g, b] = hex(h).map(lin);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}

export function oklabToSrgb([L, a, b]) {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const rgb = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];
  return rgb.map((c) =>
    Math.round(Math.min(1, Math.max(0, gam(Math.min(1, Math.max(0, c))))) * 255),
  );
}

const POS = [0, 32 / 127, 64 / 127, 96 / 127, 1];

/** 128-entry half (index 0 = near mid ... 127 = deepest) as [r,g,b] rows. */
export function halfRamp(stopsHex) {
  const ok = stopsHex.map(srgbToOklab);
  const out = [];
  for (let i = 0; i < 128; i += 1) {
    const t = i / 127;
    let k = 0;
    while (k < 3 && t > POS[k + 1]) k += 1;
    const lt = (t - POS[k]) / (POS[k + 1] - POS[k]);
    out.push(oklabToSrgb(ok[k].map((v, j) => v + (ok[k + 1][j] - v) * lt)));
  }
  return out;
}

/** 256x1 RGBA LUT (1024 bytes). convention "green-bid" (default) or "swapped". */
export function buildLut(theme = "dark", convention = "green-bid") {
  const stops = (side) =>
    [1, 2, 3, 4, 5].map((n) => resolveToken(`color.heatmap.${side}.${n}`, theme));
  const bid = halfRamp(stops("bid"));
  const ask = halfRamp(stops("ask"));
  const lut = new Uint8Array(256 * 4);
  const put = (i, [r, g, b]) => lut.set([r, g, b, 255], i * 4);
  put(
    0,
    hex(resolveToken("color.heatmap.zero", theme)).map((c) => Math.round(c * 255)),
  );
  // §3.2: lut[1..127] = bid[1..127], lut[128..255] = ask[0..127]
  for (let i = 1; i < 128; i += 1) put(i, bid[i]);
  for (let i = 0; i < 128; i += 1) put(128 + i, ask[i]);
  if (convention === "swapped") swapHalves(lut);
  return lut;
}

/** Convention swap = slice swap (no recompute): lut[i] <-> lut[128+i] for i=1..127 (ask step 0 stays). */
export function swapHalves(lut) {
  for (let i = 1; i < 128; i += 1) {
    for (let c = 0; c < 4; c += 1) {
      const a = i * 4 + c;
      const b = (128 + i) * 4 + c;
      const t = lut[a];
      lut[a] = lut[b];
      lut[b] = t;
    }
  }
  return lut;
}

export const LOG_K = 8;
export const DECAY_TAU_S = 900;

/** §3.3 intensity -> 0..1. mode "log" (default) or "linear". */
export function intensity(v, vMax, mode = "log") {
  if (v <= 0 || vMax <= 0) return 0;
  const t = mode === "linear" ? v / vMax : Math.log1p(v * LOG_K) / Math.log1p(vMax * LOG_K);
  return Math.min(1, Math.max(0, t));
}

/** Signed depth (bid > 0, ask < 0) -> LUT index. 0 = empty. */
export function lutIndex(signedDepth, vMax, mode = "log") {
  const t = intensity(Math.abs(signedDepth), vMax, mode);
  if (t === 0) return 0;
  const step = Math.min(127, Math.max(0, Math.round(t * 127)));
  return signedDepth > 0 ? Math.max(1, step) : 128 + step;
}

/** §3.4 age decay; reducedMotion = instant state (no continuous fade). */
export function decayFactor(ageS, reducedMotion = false) {
  if (reducedMotion) return ageS > 3600 ? 0 : 1;
  return Math.exp(-ageS / DECAY_TAU_S);
}

/** Legend tick -> colour the shader would produce (round-trip contract). */
export function legendTickColour(lut, v, vMax, side, mode = "log") {
  const i = lutIndex(side === "bid" ? v : -v, vMax, mode);
  return Array.from(lut.slice(i * 4, i * 4 + 3));
}
