// Bench runner (E06-K01): orchestrates a scene through a driver script,
// collecting per-frame stats and producing a report. This is what
// `pnpm bench --scenario=... --reps=...` (bench/cli.mjs) drives.
import { buildDriverScript } from "./driver.mjs";
import { summarizePercentiles, medianOfP95 } from "./stats.mjs";
import { buildReport } from "./report.mjs";
import { FRAME_STAGES } from "./instrumentation.mjs";

/**
 * Runs one repetition of a scenario against a scene, returning the raw
 * per-frame timings and the mean per-stage costs for that repetition.
 *
 * @param {{ scene: import("./scene.mjs").BenchScene, scenario: string, durationMs: number, sampleHz?: number }} opts
 */
export function runRepetition(opts) {
  const { scene, scenario, durationMs, sampleHz = 60 } = opts;
  const events = buildDriverScript({
    scenario: /** @type {any} */ (scenario),
    durationMs,
    sampleHz,
  });

  /** @type {number[]} */
  const frameTimesMs = [];
  /** @type {Record<string, number>} */
  const stageTotals = Object.fromEntries(FRAME_STAGES.map((s) => [s, 0]));
  let drawCallsLast = 0;
  let uploadedBytesLast = 0;
  let textureMemLast = 0;

  for (const event of events) {
    scene.step(event.tMs, event);
    const stats = scene.stats();
    frameTimesMs.push(stats.frameTimeMs);
    drawCallsLast = stats.drawCalls;
    uploadedBytesLast = stats.uploadedBytesPerSec;
    textureMemLast = stats.textureMemMB;
    for (const stage of FRAME_STAGES) {
      stageTotals[stage] += stats.perStageMs[stage] ?? 0;
    }
  }

  const frameCount = Math.max(1, frameTimesMs.length);
  /** @type {Record<string, number>} */
  const perStageMs = {};
  for (const stage of FRAME_STAGES) {
    perStageMs[stage] = stageTotals[stage] / frameCount;
  }

  return {
    frameTimesMs,
    perStageMs,
    drawCalls: drawCallsLast,
    uploadedBytesPerSec: uploadedBytesLast,
    textureMemMB: textureMemLast,
  };
}

/**
 * Runs `repetitions` repetitions of a scenario and produces the final
 * report, using the median of the per-repetition p95 values (§7.4's
 * "compares the median of those repeated p95s" rule) as the reported p95.
 *
 * @param {{
 *   scene: import("./scene.mjs").BenchScene,
 *   scenario: string,
 *   durationMs: number,
 *   repetitions?: number,
 *   sampleHz?: number,
 *   runtime: "chromium" | "electron" | "tauri",
 *   runtimeVersion: string,
 *   machine: import("./machine.mjs").MachineDescriptor,
 *   seed: number,
 *   lodProfile: string,
 *   peakProcessMemMB: number,
 *   peakProcessMemSource: string,
 * }} opts
 */
export function runScenario(opts) {
  const { repetitions = 3 } = opts;
  const perRep = [];
  for (let rep = 0; rep < repetitions; rep += 1) {
    perRep.push(
      runRepetition({
        scene: opts.scene,
        scenario: opts.scenario,
        durationMs: opts.durationMs,
        sampleHz: opts.sampleHz,
      }),
    );
  }

  const allFrameTimes = perRep.flatMap((r) => r.frameTimesMs);
  const p95PerRep = perRep.map((r) => summarizePercentiles(r.frameTimesMs).p95);
  const overallPercentiles = summarizePercentiles(allFrameTimes);
  // Report the median-of-p95 as the canonical p95 per §7.4; p50/p99 come
  // from the pooled distribution across reps.
  const reportedP95 = medianOfP95(p95PerRep);

  const lastRep = perRep[perRep.length - 1];
  const frameTimeMsOverall =
    allFrameTimes.reduce((sum, v) => sum + v, 0) / Math.max(1, allFrameTimes.length);

  return buildReport({
    scenario: opts.scenario,
    runtime: opts.runtime,
    runtimeVersion: opts.runtimeVersion,
    machine: opts.machine,
    seed: opts.seed,
    lodProfile: opts.lodProfile,
    repetitions,
    percentiles: { ...overallPercentiles, p95: reportedP95 },
    frameTimeMsOverall,
    perStageMs: lastRep.perStageMs,
    drawCalls: lastRep.drawCalls,
    uploadedBytesPerSec: lastRep.uploadedBytesPerSec,
    textureMemMB: lastRep.textureMemMB,
    peakProcessMemMB: opts.peakProcessMemMB,
    peakProcessMemSource: opts.peakProcessMemSource,
  });
}
