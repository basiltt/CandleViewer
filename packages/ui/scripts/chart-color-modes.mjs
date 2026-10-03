// Chart colour modes (E47-S06): the CVD-safe palette (`data-palette="cvd-safe"`)
// and the inverted buy/sell convention (`data-convention="inverted"`).
// Pure functions over a resolved theme so the CSS build, the canvas theme
// path and the tests all share one mapping.

/** Directional token pairs [positive, negative] (buy/up/bid vs sell/down/ask). */
export const DIRECTIONAL_PAIRS = [
  ["color.buy.default", "color.sell.default"],
  ["color.buy.hover", "color.sell.hover"],
  ["color.buy.subtle", "color.sell.subtle"],
  ["color.buy.hc", "color.sell.hc"],
  ["color.candle.up", "color.candle.down"],
  ["color.footprint.bid", "color.footprint.ask"],
];

/** CVD-safe source for the positive/negative side of every pair. */
const CVD_SOURCE = { positive: "color.cvd.buy", negative: "color.cvd.sell" };

/**
 * Returns the overridden token values (name -> $value) for a mode, relative
 * to the theme's own values. Empty for the default mode.
 */
export function modeOverrides(resolved, { palette = "default", convention = "standard" }) {
  /** @type {Record<string, unknown>} */
  const out = {};
  for (const [pos, neg] of DIRECTIONAL_PAIRS) {
    let p = resolved[pos]?.$value;
    let n = resolved[neg]?.$value;
    if (p === undefined || n === undefined) continue;
    if (palette === "cvd-safe") {
      p = resolved[CVD_SOURCE.positive].$value;
      n = resolved[CVD_SOURCE.negative].$value;
    }
    if (convention === "inverted") [p, n] = [n, p];
    if (palette === "default" && convention === "standard") continue;
    out[pos] = p;
    out[neg] = n;
  }
  return out;
}

export const MODES = [
  { palette: "cvd-safe", convention: "standard" },
  { palette: "default", convention: "inverted" },
  { palette: "cvd-safe", convention: "inverted" },
];

/** CSS override blocks for one theme, keyed on root data attributes. */
export function modeCss(themeName, resolved, cssValue) {
  return MODES.map((mode) => {
    const lines = Object.entries(modeOverrides(resolved, mode))
      .sort(([a], [b]) => (a < b ? -1 : 1))
      .map(
        ([name, v]) =>
          `  --${name.replace(/\./g, "-")}: ${cssValue({ $type: "color", $value: v })};`,
      );
    const sel = `[data-theme="${themeName}"][data-palette="${mode.palette}"][data-convention="${mode.convention}"]`;
    return `${sel} {\n${lines.join("\n")}\n}\n`;
  }).join("\n");
}
