#!/usr/bin/env node
// THROWAWAY PROTOTYPE (E06-K02) CLI: drives SceneA through the E06-K01
// harness's runner/report pipeline for B1/B2/B9, plus the static-frame
// scaling check and spike-preservation check this ticket's AC require.
// `node ./bench/scenes/run-scene-a.mjs --scenario=B1 --reps=3 --seed=20260928`
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { SceneA } from "./scene-a.mjs";
import { runScenario } from "../runner.mjs";
import { captureMachineDescriptor } from "../machine.mjs";
import { toSeed32 } from "../fixtures/rng.mjs";
import { generateM0Fixture } from "../fixtures/index.mjs";
import { renderMarkdownSummary } from "../report.mjs";
import { DEFAULT_REPETITIONS } from "../stats.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  const out = {};
  for (const arg of argv) {
    if (!arg.startsWith("--")) continue;
    const eq = arg.indexOf("=");
    if (eq === -1) out[arg.slice(2)] = "true";
    else out[arg.slice(2, eq)] = arg.slice(eq + 1);
  }
  return out;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const scenario = args.scenario ?? "B1";
  const repetitions = args.reps ? Number(args.reps) : DEFAULT_REPETITIONS;
  const seedInput = args.seed ?? "20260928";
  const seed = toSeed32(seedInput);
  const durationMs = args.durationMs ? Number(args.durationMs) : scenario === "B9" ? 0 : 20_000;
  const barCount = args.barCount ? Number(args.barCount) : 100_000;

  const fixture = generateM0Fixture({ seed, barCount });

  // B9: cold init to first frame, measured on a *fresh* scene instance,
  // wall-clock, separately from the steady-state per-frame report below
  // (ticket AC: "reported separately from steady-state numbers").
  const coldInitStart = nowMs();
  const coldScene = new SceneA();
  coldScene.init(fixture);
  coldScene.step(0, { tMs: 0, kind: "none" });
  const coldInitToFirstFrameMs = nowMs() - coldInitStart;
  coldScene.dispose();

  const scene = new SceneA();
  scene.init(fixture);

  const report = runScenario({
    scene,
    scenario,
    durationMs: Math.max(durationMs, 1),
    repetitions,
    runtime: "chromium",
    runtimeVersion: `node-${process.version}`,
    machine: captureMachineDescriptor({
      gpu: "none (headless Node, no GPU in this environment — see bench/scenes/README.md)",
      driver: "modelled-cost (no real GL context)",
    }),
    seed,
    lodProfile: "LOD_PROFILE_M0",
    peakProcessMemMB: Math.round(process.memoryUsage().rss / (1024 * 1024)),
    peakProcessMemSource: "process.memoryUsage().rss",
  });
  const extended = scene.extendedStats();
  scene.dispose();

  const fullReport = { ...report, coldInitToFirstFrameMs, ...extended };

  const reportPath = join(__dirname, `report-${scenario}.json`);
  writeFileSync(reportPath, JSON.stringify(fullReport, null, 2) + "\n", "utf8");
  const summaryPath = join(__dirname, `report-${scenario}.md`);
  writeFileSync(
    summaryPath,
    renderMarkdownSummary(report) +
      `\n- coldInitToFirstFrameMs: ${coldInitToFirstFrameMs.toFixed(3)}\n- lodChanges: ${extended.lodChanges}\n- barsTouched: ${extended.barsTouched}\n- currentLod: ${extended.currentLod}\n`,
    "utf8",
  );

  console.log(
    `[scene-a] scenario=${scenario} p95=${report.p95.toFixed(3)}ms drawCalls=${report.drawCalls} lodChanges=${extended.lodChanges} coldInit=${coldInitToFirstFrameMs.toFixed(3)}ms`,
  );
  console.log(`[scene-a] wrote ${reportPath}`);
  console.log(`[scene-a] wrote ${summaryPath}`);
}

function nowMs() {
  return typeof performance !== "undefined" && typeof performance.now === "function"
    ? performance.now()
    : Date.now();
}

main();
