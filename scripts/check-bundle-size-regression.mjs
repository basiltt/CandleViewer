#!/usr/bin/env node
// E02-T10: bundle-size regression check (CONSTITUTION.md §9 #15's "+5%
// regression vs `main`" rule; budget #9 of docs/plan/06-performance-and-load-
// standard.md is the absolute 8MB gzipped ceiling already enforced by
// apps/web's own `size-limit` config / `pnpm size`).
//
// size-limit itself only checks the absolute budget; it has no notion of
// "vs main". This script runs `size-limit --json`, diffs each entry's gzip
// size against a committed baseline file, and fails on >5% growth. The
// baseline is bumped by `--update` (maintainers only, mirrors the
// engine-bench baseline-update rule) after a deliberate, reviewed increase.
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");
const BASELINE_PATH = path.join(REPO_ROOT, "reports", "bundle-size-baseline.json");
const REGRESSION_PCT = 5.0;

function runSizeLimitJson(pkgFilter) {
  const result = spawnSync("npx", ["--no-install", "size-limit", "--json"], {
    cwd: path.join(REPO_ROOT, "apps", pkgFilter),
    encoding: "utf8",
    shell: process.platform === "win32",
  });
  if (result.status !== 0 && !result.stdout) {
    throw new Error(`size-limit failed for apps/${pkgFilter}: ${result.stderr}`);
  }
  return JSON.parse(result.stdout);
}

function loadBaseline() {
  if (!existsSync(BASELINE_PATH)) return {};
  return JSON.parse(readFileSync(BASELINE_PATH, "utf8"));
}

/**
 * @param {Record<string, number>} baseline
 * @param {{name: string, size: number}[]} current
 */
export function checkRegressions(baseline, current) {
  const violations = [];
  for (const entry of current) {
    const base = baseline[entry.name];
    if (base === undefined) continue; // new entry: nothing to regress against yet
    const growthPct = ((entry.size - base) / base) * 100;
    if (growthPct > REGRESSION_PCT) {
      violations.push(
        `${entry.name}: ${entry.size}B is +${growthPct.toFixed(1)}% vs baseline ${base}B (budget #15: fail on >+5%)`,
      );
    }
  }
  return violations;
}

function main() {
  const update = process.argv.includes("--update");
  const current = runSizeLimitJson("web").map((e) => ({ name: e.name, size: e.size }));
  const baseline = loadBaseline();

  if (update) {
    const next = { ...baseline };
    for (const e of current) next[e.name] = e.size;
    mkdirSync(path.dirname(BASELINE_PATH), { recursive: true });
    writeFileSync(BASELINE_PATH, JSON.stringify(next, null, 2) + "\n", "utf8");
    console.log(`check-bundle-size-regression: baseline updated at ${BASELINE_PATH}`);
    return;
  }

  const violations = checkRegressions(baseline, current);
  if (violations.length > 0) {
    console.error("check-bundle-size-regression: FAIL");
    for (const v of violations) console.error(`  - ${v}`);
    process.exit(1);
  }
  console.log("check-bundle-size-regression: OK (no entry regressed >+5% vs baseline)");
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}
