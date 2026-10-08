import { describe, expect, it } from "vitest";
import {
  compare,
  criterion1,
  criterion2,
  criterion3,
  criterion4,
  exitCriterion4,
  renderMarkdown,
} from "../../../bench/matrix/compare-matrix.mjs";
import {
  REPORT_SCHEMA,
  withinNoiseBand,
  summariseCell,
} from "../../../bench/matrix/matrix-lib.mjs";

const machine = { cpu: "cpu", gpu: "gpu", driver: "1.0", os: "win32", osBuild: "10.0.1" };
function report(runtime: string, b5p95: number) {
  return {
    schema: REPORT_SCHEMA,
    dryRun: false,
    runtime,
    seed: "1",
    fixture: { sha256: "abc" },
    driverScriptSha256: "d",
    manifest: {
      machine,
      versions: { webview2: runtime === "tauri" ? "130.0.1" : (null as string | null) },
      flagSet: { name: "x", flags: [] },
    },
    capabilities: {
      EXT_color_buffer_float: true,
      r16fSampling: true,
      instancing: true,
      offscreenCanvas: true,
    },
    cells: [
      {
        scenario: "B5",
        status: "ok",
        p50: 5,
        p95: b5p95,
        drawCalls: 15,
        admissibleForAdrEvidence: true,
      },
    ] as Array<Record<string, unknown>>,
  };
}

describe("criterion 1 (B5 p95 within 10 % of Electron, like-for-like)", () => {
  it("passes exactly at the 10 % boundary", () => {
    const r = criterion1(report("electron", 10), report("tauri", 11));
    expect(r.status).toBe("pass");
    expect(r.diffPct).toBeCloseTo(10, 9);
  });
  it("fails just above the boundary", () => {
    expect(criterion1(report("electron", 10), report("tauri", 11.01)).status).toBe("fail");
  });
  it("passes just below the boundary and when WebView2 is faster", () => {
    expect(criterion1(report("electron", 10), report("tauri", 10.99)).status).toBe("pass");
    const faster = criterion1(report("electron", 10), report("tauri", 7));
    expect(faster.status).toBe("pass");
    expect(faster.diffPct).toBeCloseTo(-30, 9);
  });
  it("records the WebView2 version beside the figure and flags it when missing", () => {
    expect(criterion1(report("electron", 10), report("tauri", 10)).webview2).toBe("130.0.1");
    const noVer = report("tauri", 10);
    noVer.manifest.versions.webview2 = null;
    expect(criterion1(report("electron", 10), noVer).note).toContain(
      "WebView2 version NOT recorded",
    );
  });
  it("is no-data (never a silent pass) when an arm lacks B5", () => {
    const empty = report("tauri", 10);
    empty.cells = [];
    expect(criterion1(report("electron", 10), empty).status).toBe("no-data");
  });
});

describe("compare() over two synthetic report files", () => {
  it("flags non-comparable runs and reports pass/fail per criterion", () => {
    const e = report("electron", 10);
    const t = { ...report("tauri", 11.5), fixture: { sha256: "different" } };
    const res = compare([e, t]);
    expect(res.comparability.ok).toBe(false);
    expect(res.rows.find((r: { id: string }) => r.id === "1")?.status).toBe("fail");
    expect(res.rows.find((r: { id: string }) => r.id === "5")?.status).toBe("manual");
    expect(res.verdict).toContain("ELECTRON CONFIRMED");
  });
  it("rejects dry-run reports", () => {
    expect(() => compare([{ ...report("electron", 1), dryRun: true }, report("tauri", 1)])).toThrow(
      /dry-run/,
    );
  });
});

describe("criteria 2 and 4", () => {
  const mk = (n: number, rt: string) => ({
    ...report(rt, 1),
    cells: [{ scenario: "B10", status: "ok", outliers33: n }],
  });
  it("fails only when outliers exist in WebView2 and are absent in Electron", () => {
    expect(criterion2(mk(0, "electron"), mk(3, "tauri")).status).toBe("fail");
    expect(criterion2(mk(2, "electron"), mk(3, "tauri")).status).toBe("pass");
    expect(criterion2(mk(2, "electron"), mk(3, "tauri")).note).toContain("engine issue");
  });
  it("requires OffscreenCanvas-in-worker evidence, not just the feature flag", () => {
    expect(criterion4(report("tauri", 1)).missing).toContain("offscreenCanvasInWorker");
  });
});

describe("matrix-lib", () => {
  it("noise band is symmetric and inclusive", () => {
    expect(withinNoiseBand(10, 10.5, 5)).toBe(true);
    expect(withinNoiseBand(10.5, 10, 5)).toBe(true);
    expect(withinNoiseBand(10, 10.6, 5)).toBe(false);
  });
  it("summariseCell keeps B7 worker and inline separate (never pooled)", () => {
    const rep = (p: number) => ({
      decodeP95Ms: p,
      drops: 0,
      duplicates: 0,
      pass: true,
      offscreenWebgl2InWorker: true,
    });
    const c = summariseCell({
      scenario: "B7",
      storm: { inline: [rep(3)], worker: [rep(1)] },
    }) as { modes: Record<string, { decodeP95Ms: number }> };
    expect(c.modes["inline"]?.decodeP95Ms).toBe(3);
    expect(c.modes["worker"]?.decodeP95Ms).toBe(1);
  });
  it("uses the median of per-repetition p95 (06 section 7.4)", () => {
    const reps = [1, 9, 2].map((p95) => ({
      p50: 1,
      p95,
      p99: 9,
      outliers33: 0,
      maxMs: 9,
      drawCalls: 4,
      mirrorP95Ms: 0,
    }));
    expect(summariseCell({ scenario: "B1", reps }).p95).toBe(2);
  });
});

describe("compare-matrix rendering and criteria 3 / exit criterion 4", () => {
  const withCells = (rt: string, cells: Array<Record<string, unknown>>) => ({
    ...report(rt, 10),
    cells,
  });
  it("criterion 3 flags progressive texSubImage2D degradation beyond tolerance", () => {
    const soak = (v: number[]) =>
      v.map((m, i) => ({ bucket: i, frames: 1, p95: 1, outliers33: 0, texUploadMedianMs: m }));
    const mk = (v: number[]) => ({
      ...report("tauri", 1),
      cells: [{ scenario: "B10", status: "ok", outliers33: 0, soak: soak(v) }],
    });
    expect(criterion3(mk([1, 1, 1, 1, 1, 1]), 10).status).toBe("pass");
    expect(criterion3(mk([1, 1, 1.5, 1.5, 2, 2]), 10).status).toBe("fail");
    expect(criterion3(mk([1, 1]), 10).status).toBe("no-data");
  });
  it("exit criterion 4 is a hard pass/fail on the 60/55 fps bar", () => {
    const b5 = (p50: number, p95: number) =>
      withCells("electron", [{ scenario: "B5", status: "ok", p50, p95, drawCalls: 15 }]);
    expect(exitCriterion4(b5(16, 18)).status).toBe("pass");
    expect(exitCriterion4(b5(17, 18)).status).toBe("fail");
    expect(exitCriterion4(b5(16, 19)).status).toBe("fail");
    expect(exitCriterion4(withCells("electron", [])).status).toBe("no-data");
  });
  it("renders a markdown table with figures, WebView2 version and verdict", () => {
    const e = report("electron", 10);
    const t = report("tauri", 10.5);
    const md = renderMarkdown(compare([e, t]), [e, t]);
    expect(md).toContain("WebView2 130.0.1");
    expect(md).toContain("| 1 |");
    expect(md).toContain("R0 exit criterion 4");
    expect(md).toContain("**Verdict:**");
  });
});
