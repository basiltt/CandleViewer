#!/usr/bin/env node
// CLI entry: `pnpm bench --scenario=B5 --runtime=electron --reps=3 --seed=...`
// (E06-K01 ticket "Runner ergonomics" bullet). Still writes bench/results.json
// (backward-compatible with E02-T03's engine-bench required-check consumer:
// frameTimeMs.{p50,p95,p99}, drawCalls, memoryMb) plus the full new report
// and its markdown summary alongside it.
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { StubScene } from "./scene.mjs";
import { runScenario } from "./runner.mjs";
import { captureMachineDescriptor } from "./machine.mjs";
import { mulberry32, toSeed32 } from "./fixtures/rng.mjs";
import { renderMarkdownSummary } from "./report.mjs";
import { DEFAULT_REPETITIONS } from "./stats.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  /** @type {Record<string, string>} */
  const out = {};
  for (const arg of argv) {
    if (!arg.startsWith("--")) continue;
    const eq = arg.indexOf("=");
    if (eq === -1) {
      out[arg.slice(2)] = "true";
    } else {
      out[arg.slice(2, eq)] = arg.slice(eq + 1);
    }
  }
  return out;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const isBaseline = args.baseline === "true";
  const scenario = args.scenario ?? "B5";
  const runtime = /** @type {"chromium"|"electron"|"tauri"} */ (args.runtime ?? "chromium");
  const repetitions = args.reps ? Number(args.reps) : DEFAULT_REPETITIONS;
  const seedInput = args.seed ?? "20260928";
  const seed = toSeed32(seedInput);
  const durationMs = args.durationMs ? Number(args.durationMs) : 1000;

  const scene = new StubScene({ seedRng: mulberry32(seed) });
  const report = runScenario({
    scene,
    scenario,
    durationMs,
    repetitions,
    runtime,
    runtimeVersion: "stub-0.0.0",
    machine: captureMachineDescriptor({
      gpu: "stub-gpu (headless run — real GPU wired by K02/K03 scene)",
      driver: "stub-driver",
    }),
    seed,
    lodProfile: "L0",
    peakProcessMemMB: Math.round(process.memoryUsage().rss / (1024 * 1024)),
    peakProcessMemSource: "process.memoryUsage().rss",
  });
  scene.dispose();

  // Backward-compatible shape for E02-T03's engine-bench required-check stub.
  const legacyResult = {
    frameTimeMs: { p50: report.p50, p95: report.p95, p99: report.p99 },
    drawCalls: report.drawCalls,
    memoryMb: report.peakProcessMemMB,
  };

  const outPath = join(__dirname, isBaseline ? "baseline.json" : "results.json");
  writeFileSync(outPath, JSON.stringify(legacyResult, null, 2) + "\n", "utf8");

  const reportPath = join(__dirname, `report-${scenario}.json`);
  writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  const summaryPath = join(__dirname, `report-${scenario}.md`);
  writeFileSync(summaryPath, renderMarkdownSummary(report), "utf8");

  console.log(`[bench] wrote ${outPath}`);
  console.log(`[bench] wrote ${reportPath}`);
  console.log(`[bench] wrote ${summaryPath}`);
}

main();
