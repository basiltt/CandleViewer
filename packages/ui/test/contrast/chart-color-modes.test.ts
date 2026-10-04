import { describe, expect, it } from "vitest";

// Plain .mjs tooling; load untyped (same pattern as data-ink.test.ts).
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const TOK = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../tokens");
const load = (f: string) => JSON.parse(readFileSync(path.join(TOK, f), "utf-8"));
/** Resolve `{a.b}` aliases over the merged primitive+semantic sets. */
function theme(files: string[]) {
  const merged: Record<string, { $value: unknown }> = Object.assign(
    {},
    load("primitives.tokens.json"),
    ...files.map(load),
  );
  const res = (v: unknown): unknown =>
    typeof v === "string" && v.startsWith("{") ? res(merged[v.slice(1, -1)]?.$value) : v;
  return Object.fromEntries(Object.entries(merged).map(([k, t]) => [k, { $value: res(t.$value) }]));
}
const loadResolvedThemes = async () => ({
  dark: theme(["semantic-dark.tokens.json"]),
  light: theme(["semantic-dark.tokens.json", "semantic-light.tokens.json"]),
  hc: theme(["semantic-dark.tokens.json", "semantic-hc.tokens.json"]),
});
const modes = (await import(
  /* @vite-ignore */ "../../scripts/chart-color-modes.mjs" as string
)) as any; // eslint-disable-line @typescript-eslint/no-explicit-any
const { modeOverrides, DIRECTIONAL_PAIRS, modeCss } = modes;

type Resolved = Record<string, { $value: unknown }>;

describe("chart colour modes", () => {
  it("inverted convention swaps every directional pair in every theme", async () => {
    const themes = (await loadResolvedThemes()) as Record<string, Resolved>;
    for (const t of Object.values(themes)) {
      const o = modeOverrides(t, { convention: "inverted" }) as Record<string, unknown>;
      for (const [pos, neg] of DIRECTIONAL_PAIRS as [string, string][]) {
        expect(o[pos]).toBe(t[neg]?.$value);
        expect(o[neg]).toBe(t[pos]?.$value);
      }
    }
  });

  it("cvd-safe palette maps buy/up/bid to cvd.buy and sell/down/ask to cvd.sell everywhere", async () => {
    const themes = (await loadResolvedThemes()) as Record<string, Resolved>;
    for (const t of Object.values(themes)) {
      const o = modeOverrides(t, { palette: "cvd-safe" }) as Record<string, unknown>;
      for (const [pos, neg] of DIRECTIONAL_PAIRS as [string, string][]) {
        expect(o[pos]).toBe(t["color.cvd.buy"]?.$value);
        expect(o[neg]).toBe(t["color.cvd.sell"]?.$value);
      }
    }
  });

  it("cvd-safe + inverted composes (swapped cvd colours)", async () => {
    const t = ((await loadResolvedThemes()) as Record<string, Resolved>)["dark"]!;
    const o = modeOverrides(t, { palette: "cvd-safe", convention: "inverted" }) as Record<
      string,
      unknown
    >;
    expect(o["color.candle.up"]).toBe(t["color.cvd.sell"]?.$value);
    expect(o["color.candle.down"]).toBe(t["color.cvd.buy"]?.$value);
  });

  it("default mode emits no overrides; css keys on data attributes", async () => {
    const t = ((await loadResolvedThemes()) as Record<string, Resolved>)["dark"]!;
    expect(modeOverrides(t, {})).toEqual({});
    const css = modeCss("dark", t, (x: { $value: unknown }) => String(x.$value)) as string;
    expect(css).toContain(
      '[data-theme="dark"][data-palette="cvd-safe"][data-convention="inverted"]',
    );
  });
});
