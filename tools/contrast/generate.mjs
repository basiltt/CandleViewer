#!/usr/bin/env node
// Contrast-matrix generator + CI gate (E05-T05).
//
// Consumes the resolved token values via `packages/ui/scripts/build-tokens.mjs`'s
// `loadResolvedThemes()` — the exact same resolution the Style Dictionary
// build step uses (`docs/plan/16-design-system-brief.md#11`) — never
// re-parses the Figma file or hand-rolls its own token resolution.
//
// Outputs `build/reports/contrast-matrix.json` and `.md` under
// `packages/ui/` (produced by the same build step per the brief). Run via
// `pnpm --filter @candleviewer/ui build:tokens && node tools/contrast/generate.mjs`,
// or the combined `pnpm --filter @candleviewer/ui contrast:gate` script.
//
// Error codes:
//   A11Y-C001 below-threshold pair
//   A11Y-C002 undeclared token (no pair/ramp/exemption entry)
//   A11Y-C003 CVD collapse (buy/sell pair or adjacent heatmap ramp stops)
//
// Exits non-zero (CI-gating) on any A11Y-C00x finding.
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { loadResolvedThemes } from "../../packages/ui/scripts/build-tokens.mjs";
import {
  contrastRatio,
  simulateCvd,
  deltaE76,
  CVD_JND_FLOOR,
  CVD_DEFICIENCIES,
} from "./color-math.mjs";
import {
  PAIRS,
  HEATMAP_RAMP,
  HEATMAP_ADJACENT_PAIRS,
  CVD_BUY_SELL_PAIR,
  collectDeclaredTokenNames,
} from "./pairs.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const UI_ROOT = path.join(REPO_ROOT, "packages", "ui");
const REPORT_DIR = path.join(UI_ROOT, "build", "reports");
const EXEMPTIONS_FILE = path.join(__dirname, "exemptions.json");

/** @param {Record<string, unknown>} theme */
function hexOf(theme, name) {
  const t = theme[name];
  if (!t) return undefined;
  return t.$value;
}

async function loadExemptions() {
  const raw = JSON.parse(await readFile(EXEMPTIONS_FILE, "utf-8"));
  const list = raw.exemptions ?? [];
  for (const e of list) {
    if (!e.reason || !e.owner || (!e.token && !e.pair)) {
      throw new Error(
        `A11Y-C002 exemptions.json entry missing token/pair/reason/owner: ${JSON.stringify(e)}`,
      );
    }
  }
  return list;
}

/** Builds the set of "fg on bg" pair keys exempted from A11Y-C001, in
 * addition to the plain undeclared-token exemptions. */
function pairExemptionKeys(exemptions) {
  return new Set(exemptions.filter((e) => e.pair).map((e) => e.pair));
}

/** Checks every declared theme's colour tokens are covered by a pair, the
 * heatmap ramp, the CVD pair, or an exemption (A11Y-C002). */
function checkUndeclaredTokens(themeName, theme, declared, exemptTokens) {
  const findings = [];
  for (const name of Object.keys(theme)) {
    if (!name.startsWith("color.")) continue;
    if (declared.has(name) || exemptTokens.has(name)) continue;
    findings.push({
      code: "A11Y-C002",
      theme: themeName,
      token: name,
      message: `A11Y-C002 undeclared token: "${name}" has no entry in tools/contrast/pairs.mjs and no exemption in tools/contrast/exemptions.json`,
    });
  }
  return findings;
}

function checkPairs(themeName, theme, pairExempt) {
  const rows = [];
  const findings = [];
  for (const { fg, bg, threshold } of PAIRS) {
    const fgHex = hexOf(theme, fg);
    const bgHex = hexOf(theme, bg);
    if (!fgHex || !bgHex) continue; // token absent from this theme (parity already gated elsewhere)
    const ratio = contrastRatio(fgHex, bgHex);
    const pass = ratio >= threshold;
    const key = `${themeName}:${fg} on ${bg}`;
    const exempt = pairExempt.has(key);
    rows.push({
      theme: themeName,
      fg,
      bg,
      fgHex,
      bgHex,
      ratio: round2(ratio),
      threshold,
      pass,
      exempt,
    });
    if (!pass && !exempt) {
      findings.push({
        code: "A11Y-C001",
        theme: themeName,
        pair: `${fg} on ${bg}`,
        ratio: round2(ratio),
        threshold,
        message: `A11Y-C001 below-threshold pair: "${fg}" on "${bg}" (${themeName}) measured ${round2(ratio)}:1, required ${threshold}:1`,
      });
    }
  }
  return { rows, findings };
}

function checkHeatmapRamp(themeName, theme, pairExempt) {
  const rows = [];
  const findings = [];
  const bgHex = hexOf(theme, HEATMAP_RAMP.bg);
  for (const stop of HEATMAP_RAMP.stops) {
    const stopHex = hexOf(theme, stop);
    if (!stopHex || !bgHex) continue;
    const ratio = contrastRatio(stopHex, bgHex);
    const pass = ratio >= HEATMAP_RAMP.threshold;
    const key = `${themeName}:${stop} on ${HEATMAP_RAMP.bg}`;
    const exempt = pairExempt.has(key);
    rows.push({
      theme: themeName,
      stop,
      bg: HEATMAP_RAMP.bg,
      ratio: round2(ratio),
      threshold: HEATMAP_RAMP.threshold,
      pass,
      exempt,
    });
    if (!pass && !exempt) {
      findings.push({
        code: "A11Y-C001",
        theme: themeName,
        pair: `${stop} on ${HEATMAP_RAMP.bg}`,
        ratio: round2(ratio),
        threshold: HEATMAP_RAMP.threshold,
        message: `A11Y-C001 below-threshold pair: heatmap stop "${stop}" on "${HEATMAP_RAMP.bg}" (${themeName}) measured ${round2(ratio)}:1, required ${HEATMAP_RAMP.threshold}:1`,
      });
    }
  }
  return { rows, findings };
}

function round2(n) {
  return Math.round(n * 100) / 100;
}

/** CVD check: buy/sell pair and adjacent heatmap ramp stops must stay
 * distinguishable (dE76 >= JND floor) under all 3 simulated deficiencies
 * (A11Y-C003). */
function checkCvd(themeName, theme, pairExempt) {
  const rows = [];
  const findings = [];

  const [buyName, sellName] = CVD_BUY_SELL_PAIR;
  const buyHex = hexOf(theme, buyName);
  const sellHex = hexOf(theme, sellName);
  if (buyHex && sellHex) {
    for (const deficiency of CVD_DEFICIENCIES) {
      const simBuy = simulateCvd(buyHex, deficiency);
      const simSell = simulateCvd(sellHex, deficiency);
      const de = deltaE76(simBuy, simSell);
      const pass = de >= CVD_JND_FLOOR;
      const key = `${themeName}:${buyName} vs ${sellName}:${deficiency}`;
      const exempt = pairExempt.has(key);
      rows.push({
        theme: themeName,
        kind: "buy-sell",
        a: buyName,
        b: sellName,
        deficiency,
        deltaE: round2(de),
        pass,
        exempt,
      });
      if (!pass && !exempt) {
        findings.push({
          code: "A11Y-C003",
          theme: themeName,
          pair: `${buyName} vs ${sellName}`,
          deficiency,
          deltaE: round2(de),
          message: `A11Y-C003 CVD collapse: "${buyName}" and "${sellName}" (${themeName}) collapse under ${deficiency} simulation (dE76 ${round2(de)} < floor ${CVD_JND_FLOOR})`,
        });
      }
    }
  }

  for (const [a, b] of HEATMAP_ADJACENT_PAIRS) {
    const aHex = hexOf(theme, a);
    const bHex = hexOf(theme, b);
    if (!aHex || !bHex) continue;
    for (const deficiency of CVD_DEFICIENCIES) {
      const simA = simulateCvd(aHex, deficiency);
      const simB = simulateCvd(bHex, deficiency);
      const de = deltaE76(simA, simB);
      const pass = de >= CVD_JND_FLOOR;
      const key = `${themeName}:${a} vs ${b}:${deficiency}`;
      const exempt = pairExempt.has(key);
      rows.push({
        theme: themeName,
        kind: "heatmap-adjacent",
        a,
        b,
        deficiency,
        deltaE: round2(de),
        pass,
        exempt,
      });
      if (!pass && !exempt) {
        findings.push({
          code: "A11Y-C003",
          theme: themeName,
          pair: `${a} vs ${b}`,
          deficiency,
          deltaE: round2(de),
          message: `A11Y-C003 CVD collapse: adjacent heatmap stops "${a}" and "${b}" (${themeName}) collapse under ${deficiency} simulation (dE76 ${round2(de)} < floor ${CVD_JND_FLOOR})`,
        });
      }
    }
  }

  return { rows, findings };
}

function toMarkdown(report) {
  const lines = [];
  lines.push("# Contrast matrix (E05-T05)");
  lines.push("");
  lines.push(
    `Generated by \`tools/contrast/generate.mjs\`. ${report.summary.pairChecks} pair checks, ` +
      `${report.summary.heatmapChecks} heatmap-stop checks, ${report.summary.cvdChecks} CVD checks. ` +
      `${report.findings.length} finding(s). Active exemptions: ${report.exemptions.length}.`,
  );
  lines.push("");

  lines.push("## Pass/fail counts per threshold class");
  lines.push("");
  lines.push("| Theme | Text (>=4.5:1) | Non-text (>=3:1) | High-contrast (>=7:1) |");
  lines.push("|---|---|---|---|");
  for (const [theme, counts] of Object.entries(report.summary.byThemeThreshold)) {
    lines.push(`| ${theme} | ${counts.text} | ${counts.nonText} | ${counts.highContrast} |`);
  }
  lines.push("");

  lines.push("## Findings");
  lines.push("");
  if (report.findings.length === 0) {
    lines.push("None.");
  } else {
    lines.push("| Code | Theme | Pair/token | Detail |");
    lines.push("|---|---|---|---|");
    for (const f of report.findings) {
      const pair = f.pair ?? f.token ?? "";
      const detail =
        f.code === "A11Y-C001"
          ? `${f.ratio}:1 measured, ${f.threshold}:1 required`
          : f.code === "A11Y-C003"
            ? `${f.deficiency}, dE76 ${f.deltaE}`
            : "no pair/exemption declared";
      lines.push(`| ${f.code} | ${f.theme} | ${pair} | ${detail} |`);
    }
  }
  lines.push("");

  lines.push(`## Active exemptions (${report.exemptions.length})`);
  lines.push("");
  if (report.exemptions.length === 0) {
    lines.push("None.");
  } else {
    lines.push("| Token / pair | Reason | Owner |");
    lines.push("|---|---|---|");
    for (const e of report.exemptions) {
      lines.push(`| ${e.token ?? e.pair} | ${e.reason} | ${e.owner} |`);
    }
  }
  lines.push("");
  return lines.join("\n");
}

async function main() {
  const themes = await loadResolvedThemes();
  const exemptions = await loadExemptions();
  const exemptTokens = new Set(exemptions.map((e) => e.token));
  const pairExempt = pairExemptionKeys(exemptions);
  const declared = collectDeclaredTokenNames();

  const allFindings = [];
  const allPairRows = [];
  const allHeatmapRows = [];
  const allCvdRows = [];
  const byThemeThreshold = {};

  for (const [themeName, theme] of Object.entries(themes)) {
    allFindings.push(...checkUndeclaredTokens(themeName, theme, declared, exemptTokens));

    const { rows: pairRows, findings: pairFindings } = checkPairs(themeName, theme, pairExempt);
    allPairRows.push(...pairRows);
    allFindings.push(...pairFindings);

    const { rows: heatmapRows, findings: heatmapFindings } = checkHeatmapRamp(
      themeName,
      theme,
      pairExempt,
    );
    allHeatmapRows.push(...heatmapRows);
    allFindings.push(...heatmapFindings);

    const { rows: cvdRows, findings: cvdFindings } = checkCvd(themeName, theme, pairExempt);
    allCvdRows.push(...cvdRows);
    allFindings.push(...cvdFindings);

    const counts = { text: 0, nonText: 0, highContrast: 0 };
    for (const row of [...pairRows, ...heatmapRows]) {
      if (row.threshold >= 7) counts.highContrast += row.pass ? 1 : 0;
      else if (row.threshold >= 4.5) counts.text += row.pass ? 1 : 0;
      else counts.nonText += row.pass ? 1 : 0;
    }
    byThemeThreshold[themeName] = counts;
  }

  const report = {
    generatedBy: "tools/contrast/generate.mjs",
    thresholds: { text: 4.5, nonText: 3.0, highContrast: 7.0 },
    summary: {
      pairChecks: allPairRows.length,
      heatmapChecks: allHeatmapRows.length,
      cvdChecks: allCvdRows.length,
      byThemeThreshold,
    },
    pairs: allPairRows,
    heatmap: allHeatmapRows,
    cvd: allCvdRows,
    exemptions,
    findings: allFindings,
  };

  await mkdir(REPORT_DIR, { recursive: true });
  await writeFile(
    path.join(REPORT_DIR, "contrast-matrix.json"),
    JSON.stringify(report, null, 2) + "\n",
    "utf-8",
  );
  await writeFile(path.join(REPORT_DIR, "contrast-matrix.md"), toMarkdown(report), "utf-8");

  console.log(
    `[contrast-gate] ${allFindings.length} finding(s); ${exemptions.length} active exemption(s); ` +
      `${allPairRows.length} pair checks, ${allHeatmapRows.length} heatmap checks, ${allCvdRows.length} CVD checks.`,
  );
  for (const e of exemptions) {
    console.log(
      `[contrast-gate] exemption: ${e.token ?? e.pair} — ${e.reason} (owner: ${e.owner})`,
    );
  }
  for (const f of allFindings) {
    console.error(`[contrast-gate] ${f.message}`);
  }

  if (allFindings.length > 0) {
    process.exitCode = 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((err) => {
    console.error(err.stack ?? err.message ?? err);
    process.exitCode = 1;
  });
}

export {
  loadResolvedThemes,
  checkUndeclaredTokens,
  checkPairs,
  checkHeatmapRamp,
  checkCvd,
  loadExemptions,
  toMarkdown,
};
