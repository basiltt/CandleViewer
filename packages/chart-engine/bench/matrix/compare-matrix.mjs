#!/usr/bin/env node
// E06-T01 — ADR-0011 criteria table from 2-3 matrix report files.
//   node bench/matrix/compare-matrix.mjs <electron.json> <tauri.json> [chromium.json]
//        [--degradation-tolerance <pct>] [--json] [--out <file.md>]
// Runtimes are identified by each report's own `runtime` field, not by argument order.
// Pass/fail is computed ONLY from measured figures; a missing figure is "no-data"
// (never silently a pass). Criterion 5 is a checklist (E10-K01 / E06-X01), not a number,
// so it is reported "manual" and never counted as an automatic pass.
import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { ADR_0011, REPORT_SCHEMA } from "./matrix-lib.mjs";
import { B5_GATES } from "./scenes/b5-combined.mjs";

const EPS = 1e-9;
const cell = (report, scenario) => report?.cells?.find((c) => c.scenario === scenario);
const fmt = (v, d = 2) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : "n/a");

/**
 * Criterion 1: B5 p95 in WebView2 within `pct` % of Electron, like-for-like. The signed
 * difference is (tauri - electron) / electron: WebView2 being FASTER always passes; being
 * slower passes iff <= pct. The boundary (exactly pct %) passes ("within 10 %").
 * @returns {{ status: "pass"|"fail"|"no-data", diffPct: number|null, electronP95: number|null, tauriP95: number|null, webview2: string|null, note: string }}
 */
export function criterion1(electron, tauri, pct = ADR_0011.b5ParityPct) {
  const e = cell(electron, "B5");
  const t = cell(tauri, "B5");
  const webview2 = tauri?.manifest?.versions?.webview2 ?? null;
  if (!(e?.p95 > 0) || !(t?.p95 > 0)) {
    return {
      status: "no-data",
      diffPct: null,
      electronP95: e?.p95 ?? null,
      tauriP95: t?.p95 ?? null,
      webview2,
      note: "B5 p95 missing in one arm",
    };
  }
  const diffPct = ((t.p95 - e.p95) / e.p95) * 100;
  const caveats = [];
  if (!e.admissibleForAdrEvidence || !t.admissibleForAdrEvidence)
    caveats.push("fewer than 3 repetitions");
  if (!webview2) caveats.push("WebView2 version NOT recorded");
  return {
    status: diffPct <= pct + EPS ? "pass" : "fail",
    diffPct,
    electronP95: e.p95,
    tauriP95: t.p95,
    webview2,
    note: caveats.join("; "),
  };
}

/** Criterion 2: outliers > 33 ms in the Tauri soak that are absent under Electron. */
export function criterion2(electron, tauri) {
  const e = cell(electron, "B10");
  const t = cell(tauri, "B10");
  if (e?.status !== "ok" || t?.status !== "ok") {
    return {
      status: "no-data",
      electronOutliers: e?.outliers33 ?? null,
      tauriOutliers: t?.outliers33 ?? null,
      note: "B10 missing in one arm",
    };
  }
  const eo = e.outliers33;
  const to = t.outliers33;
  let note = "";
  if (to > 0 && eo > 0)
    note = "outliers present in BOTH runtimes: investigate as an engine issue, not a shell issue";
  return {
    status: to > 0 && eo === 0 ? "fail" : "pass",
    electronOutliers: eo,
    tauriOutliers: to,
    note,
  };
}

/**
 * Criterion 3: texSubImage2D 10 Hz streaming shows no progressive degradation. Compares the
 * median of the per-minute upload medians in the last third of the soak against the first
 * third. The ADR states no number; the tolerance is an explicit, overridable assumption.
 */
export function criterion3(tauri, tolerancePct = ADR_0011.degradationTolerancePct) {
  const t = cell(tauri, "B10");
  const buckets = (t?.soak ?? []).filter((b) => b.texUploadMedianMs != null);
  if (t?.status !== "ok" || buckets.length < 3) {
    return {
      status: "no-data",
      driftPct: null,
      tolerancePct,
      note: "needs a >= 3 minute B10 soak with upload samples",
    };
  }
  const third = Math.max(1, Math.floor(buckets.length / 3));
  const med = (xs) => {
    const s = xs.map((b) => b.texUploadMedianMs).sort((a, b) => a - b);
    const m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  };
  const first = med(buckets.slice(0, third));
  const last = med(buckets.slice(-third));
  if (!(first > 0))
    return {
      status: "no-data",
      driftPct: null,
      tolerancePct,
      note: "first-third upload median is zero (timer resolution)",
    };
  const driftPct = ((last - first) / first) * 100;
  return {
    status: driftPct <= tolerancePct + EPS ? "pass" : "fail",
    driftPct,
    tolerancePct,
    firstMs: first,
    lastMs: last,
    note: `tolerance ${tolerancePct}% is an analyst assumption, ADR gives no figure`,
  };
}

/** Criterion 4: WebGL2 capability parity in the Tauri arm (all five must be true). */
export function criterion4(tauri) {
  const c = tauri?.capabilities;
  if (!c)
    return { status: "no-data", missing: [], note: "no capability probe in the Tauri report" };
  const need = {
    EXT_color_buffer_float: c.EXT_color_buffer_float,
    R16F: c.r16fSampling,
    instancing: c.instancing,
    offscreenCanvas: c.offscreenCanvas,
  };
  const worker = cell(tauri, "B7")?.modes?.worker;
  need.offscreenCanvasInWorker = worker ? worker.offscreenWebgl2InWorker === true : false;
  const missing = Object.entries(need)
    .filter(([, v]) => !v)
    .map(([k]) => k);
  return {
    status: missing.length ? "fail" : "pass",
    missing,
    note: missing.length
      ? "gap is a RESULT; affected scenarios must be labelled reduced/degraded-2d"
      : "",
  };
}

/** R0 exit criterion 4 (roadmap §4.3) on Electron's B5, plus the B5 gates. */
export function exitCriterion4(electron) {
  const b = cell(electron, "B5");
  if (b?.status !== "ok") return { status: "no-data", note: "B5 missing in Electron report" };
  const g = B5_GATES.exitCriterion4;
  const p50ok = b.p50 <= g.p50FrameMs + EPS;
  const p95ok = b.p95 <= g.p95FrameMs + EPS;
  const gateP95 = b.p95 <= B5_GATES.p95FrameMs + EPS;
  const draws = b.drawCalls <= B5_GATES.maxDrawCalls;
  return {
    status: p50ok && p95ok ? "pass" : "fail",
    p50: b.p50,
    p95: b.p95,
    drawCalls: b.drawCalls,
    p50fps: 1000 / b.p50,
    p95fps: 1000 / b.p95,
    b5GateP95: gateP95,
    b5GateDrawCalls: draws,
    note: `bar: p50 >= 60 fps (<= ${fmt(g.p50FrameMs)} ms), p95 >= 55 fps (<= ${fmt(g.p95FrameMs)} ms); B5 gates p95 <= ${B5_GATES.p95FrameMs} ms and <= ${B5_GATES.maxDrawCalls} draws`,
  };
}

export function compare(reports, opts = {}) {
  const by = {};
  for (const r of reports) {
    if (r.schema !== REPORT_SCHEMA) throw new Error(`unsupported report schema ${r.schema}`);
    if (r.dryRun) throw new Error(`${r.runtime} report is a --dry-run; it carries no measurements`);
    by[r.runtime] = r;
  }
  const { electron, tauri, chromium } = by;
  const same = [];
  const fx = reports.map((r) => r.fixture?.sha256 ?? null);
  const seeds = reports.map((r) => r.seed);
  const drv = reports.map((r) => r.driverScriptSha256 ?? null);
  const sameAll = (xs) => xs.every((x) => x !== null && x === xs[0]);
  if (!sameAll(fx)) same.push("fixture sha256 differs or is missing");
  if (!sameAll(seeds.map(String))) same.push("seed differs");
  if (!sameAll(drv)) same.push("driver script hash differs");
  const machines = new Set(
    reports.map(
      (r) =>
        `${r.manifest?.machine?.cpu}|${r.manifest?.machine?.gpu}|${r.manifest?.machine?.driver}`,
    ),
  );
  if (machines.size > 1) same.push("machine descriptor differs (not a same-machine comparison)");
  const rows = [
    { id: "1", title: "B5 p95 WebView2 within 10 % of Electron", ...criterion1(electron, tauri) },
    {
      id: "2",
      title: "No >33 ms soak outliers absent under Electron (B10)",
      ...criterion2(electron, tauri),
    },
    {
      id: "3",
      title: "texSubImage2D 10 Hz: no progressive degradation (B10)",
      ...criterion3(tauri, opts.degradationTolerancePct),
    },
    {
      id: "4",
      title:
        "WebGL2 capability parity (EXT_color_buffer_float, R16F, instancing, OffscreenCanvas in worker)",
      ...criterion4(tauri),
    },
    {
      id: "5",
      title: "Shell responsibility parity",
      status: "manual",
      note: "checklist from E06-X01 / E10-K01 (docs/plan/spikes/E10-K01.md): cannot be computed from frame data",
    },
  ];
  const auto = rows.filter((r) => r.status !== "manual");
  const verdict = auto.some((r) => r.status === "fail")
    ? "ELECTRON CONFIRMED (>=1 criterion failed)"
    : auto.every((r) => r.status === "pass")
      ? "Tauri not ruled out by criteria 1-4 (criterion 5 still manual)"
      : "INCOMPLETE (no-data in >=1 criterion)";
  return {
    comparability: { ok: same.length === 0, problems: same },
    rows,
    exitCriterion4: exitCriterion4(electron),
    verdict,
    runtimesPresent: Object.keys(by),
    chromiumPresent: Boolean(chromium),
  };
}

export function renderMarkdown(res, reports) {
  const L = [
    "# E06-T01 matrix: ADR-0011 criteria",
    "",
    `Runtimes: ${res.runtimesPresent.join(", ")} | Comparable: ${res.comparability.ok ? "yes" : "NO — " + res.comparability.problems.join("; ")}`,
    "",
    "| # | Criterion | Figure | Result |",
    "|---|---|---|---|",
  ];
  for (const r of res.rows) {
    let fig = "";
    if (r.id === "1")
      fig = `Electron ${fmt(r.electronP95)} ms vs WebView2 ${fmt(r.tauriP95)} ms = ${fmt(r.diffPct, 1)} % (threshold 10 %); WebView2 ${r.webview2 ?? "VERSION MISSING"}`;
    if (r.id === "2")
      fig = `outliers >33 ms: Electron ${r.electronOutliers ?? "n/a"}, WebView2 ${r.tauriOutliers ?? "n/a"}`;
    if (r.id === "3")
      fig =
        r.driftPct == null
          ? "n/a"
          : `upload median ${fmt(r.firstMs, 3)} -> ${fmt(r.lastMs, 3)} ms = ${fmt(r.driftPct, 1)} % drift (tolerance ${r.tolerancePct} %)`;
    if (r.id === "4") fig = r.missing?.length ? `missing: ${r.missing.join(", ")}` : "all present";
    L.push(
      `| ${r.id} | ${r.title} | ${fig}${r.note ? " — " + r.note : ""} | **${r.status.toUpperCase()}** |`,
    );
  }
  const x = res.exitCriterion4;
  L.push(
    "",
    `**R0 exit criterion 4 (Electron B5):** ${x.status.toUpperCase()}` +
      (x.p50
        ? ` — p50 ${fmt(x.p50)} ms (${fmt(x.p50fps, 1)} fps), p95 ${fmt(x.p95)} ms (${fmt(x.p95fps, 1)} fps), ${x.drawCalls} draw calls; B5 gates p95<=16.7: ${x.b5GateP95}, draws<=40: ${x.b5GateDrawCalls}`
        : ` — ${x.note}`),
  );
  L.push("", `**Verdict:** ${res.verdict}`, "");
  for (const r of reports) {
    const m = r.manifest;
    L.push(
      `- ${r.runtime}: ${m.machine.cpu} / ${m.machine.gpu} (${m.machine.driver}) / ${m.machine.os} ${m.machine.osBuild} / Electron ${m.versions.electron ?? "-"} Chromium ${m.versions.chromium ?? "-"} Tauri ${m.versions.tauri ?? "-"} WebView2 ${m.versions.webview2 ?? "-"} Node ${m.versions.node}; flags: ${m.flagSet.name}; seed ${r.seed}; fixture sha256 ${r.fixture?.sha256 ?? "n/a"}`,
    );
  }
  return L.join("\n") + "\n";
}

function main() {
  const argv = process.argv.slice(2);
  const files = [];
  const opts = {};
  let json = false;
  let out = null;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--degradation-tolerance") opts.degradationTolerancePct = Number(argv[++i]);
    else if (argv[i] === "--json") json = true;
    else if (argv[i] === "--out") out = argv[++i];
    else files.push(argv[i]);
  }
  if (files.length < 2 || files.length > 3) {
    console.error(
      "usage: compare-matrix.mjs <report> <report> [<report>] [--json] [--out file.md]",
    );
    process.exit(2);
  }
  const reports = files.map((f) => JSON.parse(readFileSync(f, "utf8")));
  const res = compare(reports, opts);
  const text = json ? JSON.stringify(res, null, 2) + "\n" : renderMarkdown(res, reports);
  if (out) writeFileSync(out, text);
  process.stdout.write(text);
  process.exit(res.rows.some((r) => r.status === "fail") ? 1 : 0);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
