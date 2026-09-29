// Custom Style Dictionary format: `json/flat`.
//
// Produces `build/electron/tokens.main.json` per
// docs/plan/16-design-system-brief.md §11: a single-level key→value JSON
// map, parseable without any CSS or TypeScript tooling, for the Electron
// main process (title-bar colour, tray-icon theme, OS dark/light hint).
//
// Values are the fully-resolved primitive (Style Dictionary resolves
// `{alias}` references before formats run), stringified as-is: colours
// stay hex strings, dimensions stay their resolved string/number.

/**
 * @param {{ dictionary: { allTokens: Array<{ name: string, value: unknown }> } }} args
 */
export default function jsonFlat({ dictionary }) {
  const out = {};
  const sorted = [...dictionary.allTokens].sort((a, b) => a.name.localeCompare(b.name));
  for (const token of sorted) {
    out[token.name] = flattenValue(token.value);
  }
  return JSON.stringify(out, null, 2) + "\n";
}

/** Typography/shadow tokens are objects; keep them as plain nested JSON. */
function flattenValue(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const nested = {};
    for (const k of Object.keys(value).sort()) {
      nested[k] = flattenValue(value[k]);
    }
    return nested;
  }
  return value;
}
