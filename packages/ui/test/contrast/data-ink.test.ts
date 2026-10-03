import { describe, expect, it } from "vitest";

// Plain .mjs tooling lives outside the package; load it untyped.
const lib = (await import(
  /* @vite-ignore */ "../../../../tools/contrast/data-ink-lib.mjs" as string
)) as any; // eslint-disable-line @typescript-eslint/no-explicit-any
const math = (await import(
  /* @vite-ignore */ "../../../../tools/contrast/color-math.mjs" as string
)) as any; // eslint-disable-line @typescript-eslint/no-explicit-any

const tok = (v: string) => ({ $type: "color", $value: v });

function theme(over: Record<string, string> = {}) {
  const base: Record<string, string> = {
    "color.surface.canvas": "#000000",
    "color.heatmap.zero": "#000000",
    "color.heatmap.bid.1": "#00FF00",
    "color.heatmap.bid.2": "#00FF00",
    "color.heatmap.bid.3": "#00FF00",
    "color.heatmap.bid.4": "#00FF00",
    "color.heatmap.bid.5": "#00FF00",
    ...over,
  };
  return Object.fromEntries(Object.entries(base).map(([k, v]) => [k, tok(v)]));
}

describe("contrast math reference values", () => {
  it("black/white is 21:1", () => {
    expect(math.contrastRatio("#000000", "#FFFFFF")).toBeCloseTo(21, 5);
  });
  it("#777777 on white is ~4.48:1", () => {
    expect(math.contrastRatio("#777777", "#FFFFFF")).toBeCloseTo(4.48, 2);
  });
  it("deuteranopia leaves greys unchanged and collapses pure red/green closer", () => {
    expect(math.simulateCvd("#808080", "deuteranopia")).toBe("#808080");
    const de = math.deltaE76(
      math.simulateCvd("#FF0000", "deuteranopia"),
      math.simulateCvd("#00FF00", "deuteranopia"),
    );
    expect(de).toBeLessThan(math.deltaE76("#FF0000", "#00FF00"));
  });
});

describe("gradient sampling", () => {
  it("samples N>=16 stops with exact endpoints", () => {
    const s = lib.sampleRamp(["#000000", "#FFFFFF"], 16);
    expect(s).toHaveLength(16);
    expect(s[0].hex).toBe("#000000");
    expect(s[15].hex).toBe("#FFFFFF");
  });
  it("rejects fewer than 2 stops", () => {
    expect(() => lib.sampleRamp(["#000000", "#FFFFFF"], 1)).toThrow(/A11Y-C000/);
  });
  it("a single failing stop fails the ramp and reports position and ratio", () => {
    const rows = lib.evaluate({ dark: theme() }, { stops: 16 });
    const sum = lib.summarise(rows);
    const ramp = sum.ramps.find((r: { id: string }) => r.id === "heatmap.bid");
    expect(ramp.stops).toBe(16);
    expect(ramp.pass).toBe(false); // starts at canvas colour -> 1:1
    expect(ramp.failing[0]).toEqual({ pos: 0, ratio: 1 });
  });
  it("a known-good ramp passes at every stop", () => {
    const rows = lib.evaluate(
      { dark: theme({ "color.heatmap.zero": "#FFFFFF", "color.heatmap.bid.1": "#FFFFFF" }) },
      { stops: 16 },
    );
    const ramp = lib.summarise(rows).ramps.find((r: { id: string }) => r.id === "heatmap.bid");
    expect(ramp.pass).toBe(true);
  });
});

describe("CVD discriminability", () => {
  it("a collapsing pair fails with both simulated values reported", () => {
    const rows = lib.evaluate(
      { dark: theme({ "color.buy.default": "#808080", "color.sell.default": "#818181" }) },
      { stops: 16 },
    );
    const r = rows.find(
      (x: { kind: string; id: string; deficiency: string }) =>
        x.kind === "cvd" &&
        x.id === "color.buy.default vs color.sell.default" &&
        x.deficiency === "deuteranopia",
    );
    expect(r.pass).toBe(false);
    expect(r.simulatedA).toMatch(/^#[0-9A-F]{6}$/);
    expect(r.simulatedB).toMatch(/^#[0-9A-F]{6}$/);
  });
  it("a distinct pair passes", () => {
    const rows = lib.evaluate(
      { dark: theme({ "color.buy.default": "#0000FF", "color.sell.default": "#FFFF00" }) },
      { stops: 16 },
    );
    const r = rows.filter(
      (x: { id: string }) => x.id === "color.buy.default vs color.sell.default",
    );
    expect(r).toHaveLength(3);
    expect(r.every((x: { pass: boolean }) => x.pass)).toBe(true);
  });
});

describe("theme and density thresholds", () => {
  const text = {
    "color.surface.app": "#000000",
    "color.text.primary": "#FFFFFF",
    "color.text.secondary": "#767676", // ~4.5-ish vs black: passes AA, fails 7:1
    "color.surface.canvas": "#000000",
    "color.axis.text": "#6E6E6E", // ~3.9 vs black: passes 3:1, fails 4.5:1
  };
  it("high-contrast holds body text to 7:1 and only in its own column", () => {
    const rows = lib.evaluate({ dark: theme(text), "high-contrast": theme(text) }, { stops: 16 });
    const key = "color.text.secondary on color.surface.app";
    const dark = rows.find(
      (x: { theme: string; density: string; id: string }) =>
        x.theme === "dark" && x.density === "comfortable" && x.id === key,
    );
    const hc = rows.find(
      (x: { theme: string; density: string; id: string }) =>
        x.theme === "high-contrast" && x.density === "comfortable" && x.id === key,
    );
    expect(dark.threshold).toBe(4.5);
    expect(dark.pass).toBe(true);
    expect(hc.threshold).toBe(7);
    expect(hc.pass).toBe(false);
  });
  it("compact density raises the large-text pair to 4.5:1", () => {
    const rows = lib.evaluate({ dark: theme(text) }, { stops: 16 });
    const id = "color.axis.text on color.surface.canvas";
    const comfy = rows.find(
      (x: { density: string; id: string }) => x.density === "comfortable" && x.id === id,
    );
    const compact = rows.find(
      (x: { density: string; id: string }) => x.density === "compact" && x.id === id,
    );
    expect(comfy.threshold).toBe(3);
    expect(comfy.pass).toBe(true);
    expect(compact.threshold).toBe(4.5);
    expect(compact.pass).toBe(false);
  });
});

describe("generated matrix", () => {
  it("is markdown with explicit PASS/FAIL words", () => {
    const rows = lib.evaluate({ dark: theme() }, { stops: 16 });
    const md = lib.toMarkdown(rows, 16) as string;
    expect(md).toContain("| FAIL |");
    expect(md).toMatch(/Gradient ramps/);
  });
});
