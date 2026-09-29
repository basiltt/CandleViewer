// Report writer + JSON schema (E06-K01 ticket "Report writer" bullet).
// Schema shared with E06-D02's counter vocabulary (SCR-046) — this file is
// the source of truth for that contract until E06-D02 lands its own copy.
import { FRAME_STAGES } from "./instrumentation.mjs";
import { isAdmissible } from "./stats.mjs";
import { assertDescriptorComplete } from "./machine.mjs";

/** GPU flags pinned for headless Chromium runs (ticket "Flag set… must be pinned and printed"). */
export const PINNED_CHROMIUM_FLAGS = Object.freeze([
  "--use-gl=angle",
  "--use-angle=swiftshader",
  "--disable-gpu-vsync",
  "--enable-webgl2",
  "--force-color-profile=srgb",
]);

/**
 * @typedef {{
 *   scenario: string,
 *   runtime: "chromium" | "electron" | "tauri",
 *   runtimeVersion: string,
 *   gpuFlags: readonly string[],
 *   machine: import("./machine.mjs").MachineDescriptor,
 *   seed: number,
 *   lodProfile: string,
 *   repetitions: number,
 *   admissibleForAdrEvidence: boolean,
 *   p50: number,
 *   p95: number,
 *   p99: number,
 *   perStageMs: Record<string, number>,
 *   unattributedMs: number,
 *   drawCalls: number,
 *   uploadedBytesPerSec: number,
 *   textureMemMB: number,
 *   textureMemIsEstimate: boolean,
 *   peakProcessMemMB: number,
 *   peakProcessMemSource: string,
 * }} BenchReport
 */

/**
 * Builds the run report object described by the ticket:
 * `{scenario, runtime, runtimeVersion, gpu, driver, os, seed, lodProfile,
 * repetitions, p50, p95, p99, perStageMs{}, drawCalls, uploadedBytesPerSec,
 * textureMemMB, peakProcessMemMB}`.
 *
 * @param {{
 *   scenario: string,
 *   runtime: BenchReport["runtime"],
 *   runtimeVersion: string,
 *   machine: import("./machine.mjs").MachineDescriptor,
 *   seed: number,
 *   lodProfile: string,
 *   repetitions: number,
 *   percentiles: { p50: number, p95: number, p99: number },
 *   frameTimeMsOverall: number,
 *   perStageMs: Record<string, number>,
 *   drawCalls: number,
 *   uploadedBytesPerSec: number,
 *   textureMemMB: number,
 *   textureMemIsEstimate?: boolean,
 *   peakProcessMemMB: number,
 *   peakProcessMemSource: string,
 * }} input
 * @returns {BenchReport}
 */
export function buildReport(input) {
  assertDescriptorComplete(input.machine);

  const stageSum = FRAME_STAGES.reduce((sum, stage) => sum + (input.perStageMs[stage] ?? 0), 0);
  const unattributedMs = Math.max(0, input.frameTimeMsOverall - stageSum);
  const residualFraction =
    input.frameTimeMsOverall > 0 ? unattributedMs / input.frameTimeMsOverall : 0;
  if (residualFraction > 0.1) {
    throw new Error(
      `[bench] stage costs sum to ${stageSum.toFixed(2)}ms but frame time was ` +
        `${input.frameTimeMsOverall.toFixed(2)}ms — unattributed residual ` +
        `${(residualFraction * 100).toFixed(1)}% exceeds the ticket's 10% ceiling`,
    );
  }

  return {
    scenario: input.scenario,
    runtime: input.runtime,
    runtimeVersion: input.runtimeVersion,
    gpuFlags: PINNED_CHROMIUM_FLAGS,
    machine: input.machine,
    seed: input.seed,
    lodProfile: input.lodProfile,
    repetitions: input.repetitions,
    admissibleForAdrEvidence: isAdmissible(input.repetitions),
    p50: input.percentiles.p50,
    p95: input.percentiles.p95,
    p99: input.percentiles.p99,
    perStageMs: input.perStageMs,
    unattributedMs,
    drawCalls: input.drawCalls,
    uploadedBytesPerSec: input.uploadedBytesPerSec,
    textureMemMB: input.textureMemMB,
    textureMemIsEstimate: input.textureMemIsEstimate ?? true,
    peakProcessMemMB: input.peakProcessMemMB,
    peakProcessMemSource: input.peakProcessMemSource,
  };
}

/**
 * Renders a human-readable markdown summary of a report (ticket:
 * "plus a human-readable markdown summary").
 * @param {BenchReport} report
 */
export function renderMarkdownSummary(report) {
  const lines = [
    `# Bench report — ${report.scenario} (${report.runtime} ${report.runtimeVersion})`,
    "",
    `Seed: \`${report.seed}\` · LOD profile: \`${report.lodProfile}\` · Repetitions: ${report.repetitions}` +
      (report.admissibleForAdrEvidence
        ? ""
        : " **(NOT admissible for ADR evidence — need >= 3 reps)**"),
    "",
    `| Metric | Value |`,
    `|---|---|`,
    `| p50 frame time | ${report.p50.toFixed(2)} ms |`,
    `| p95 frame time | ${report.p95.toFixed(2)} ms |`,
    `| p99 frame time | ${report.p99.toFixed(2)} ms |`,
    `| Draw calls | ${report.drawCalls} |`,
    `| Uploaded bytes/sec | ${report.uploadedBytesPerSec} |`,
    `| Texture memory (MB${report.textureMemIsEstimate ? ", estimate" : ""}) | ${report.textureMemMB} |`,
    `| Peak process memory (MB, source: ${report.peakProcessMemSource}) | ${report.peakProcessMemMB} |`,
    "",
    "## Per-stage attribution (ms/frame, mean)",
    "",
    "| Stage | ms |",
    "|---|---|",
    ...FRAME_STAGES.map((stage) => `| ${stage} | ${(report.perStageMs[stage] ?? 0).toFixed(3)} |`),
    `| unattributed | ${report.unattributedMs.toFixed(3)} |`,
    "",
    `Machine: ${report.machine.cpu} / ${report.machine.gpu} (driver ${report.machine.driver}) / ` +
      `${report.machine.os} ${report.machine.osBuild}` +
      (report.machine.webview2Version ? ` / WebView2 ${report.machine.webview2Version}` : ""),
    "",
    `GPU flags: \`${report.gpuFlags.join(" ")}\``,
    "",
  ];
  return lines.join("\n");
}
