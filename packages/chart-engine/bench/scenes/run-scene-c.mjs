#!/usr/bin/env node
// THROWAWAY PROTOTYPE (E06-K04) CLI: B4, trail-length experiment, 5x message
// coalescing, cadence ladder, price-origin shift, LUT swap, capability profiles,
// B10 soak (simulated clock, real memory sampling) with mid-soak context loss.
// `node ./bench/scenes/run-scene-c.mjs --reps=3 --durationMs=20000 --soakMin=30`
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { SceneC, FULL_CAPS } from "./scene-c.mjs";
import { runScenario } from "../runner.mjs";
import { buildDriverScript } from "../driver.mjs";
import { captureMachineDescriptor } from "../machine.mjs";
import { toSeed32 } from "../fixtures/rng.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const args = Object.fromEntries(
  process.argv
    .slice(2)
    .filter((a) => a.startsWith("--"))
    .map((a) => {
      const [k, v = "true"] = a.slice(2).split("=");
      return [k, v];
    }),
);
const reps = Number(args.reps ?? 3);
const durationMs = Number(args.durationMs ?? 20_000);
const soakMin = Number(args.soakMin ?? 30);
const seed = toSeed32(args.seed ?? "20260928");
const machine = captureMachineDescriptor({ gpu: "none (headless Node)", driver: "modelled-cost" });
const rss = () => Math.round(process.memoryUsage().rss / 1048576);

function b4(opts, label) {
  const scene = new SceneC(opts);
  scene.init();
  const report = runScenario({
    scene,
    scenario: "B4",
    durationMs,
    repetitions: reps,
    runtime: "chromium",
    runtimeVersion: `node-${process.version}`,
    machine,
    seed,
    lodProfile: "LOD_PROFILE_M0",
    peakProcessMemMB: rss(),
    peakProcessMemSource: "process.memoryUsage().rss",
  });
  const ext = scene.extendedStats();
  scene.dispose();
  return {
    label,
    p95: report.p95,
    p99: report.p99,
    uploadedBytesPerSec: report.uploadedBytesPerSec,
    textureMemMB: report.textureMemMB,
    drawCalls: report.drawCalls,
    perStageMs: report.perStageMs,
    ext,
  };
}

const out = { machine, node: process.version, reps, durationMs };
out.b4 = b4({ trailMs: 4 * 3600_000 }, "4h trail, 1s coarse");
out.b4Coarse2s = b4({ trailMs: 4 * 3600_000, coarseStepMs: 2000 }, "4h trail, 2s coarse");

// Constant upload vs trail length.
out.trailExperiment = [5 * 60_000, 3600_000, 4 * 3600_000].map((trailMs) => {
  const r = b4({ trailMs }, `${trailMs / 60000} min`);
  return { trailMin: trailMs / 60000, p95: r.p95, uploadedBytesPerSec: r.uploadedBytesPerSec };
});

// 5x message rate coalescing + degradation lever (cadence 250 ms).
const base = b4({}, "1x");
const x5 = b4({ msgMult: 5 }, "5x msgs");
out.coalescing = {
  x1: { msgs: base.ext.msgs, upBps: base.uploadedBytesPerSec },
  x5: { msgs: x5.ext.msgs, upBps: x5.uploadedBytesPerSec },
};
const c250 = b4({ cadenceMs: 250 }, "250ms cadence");
out.cadence250 = {
  p95: c250.p95,
  uploadedBytesPerSec: c250.uploadedBytesPerSec,
  stage: c250.perStageMs.heatmapUpload,
};
out.cadence100 = {
  p95: base.p95,
  uploadedBytesPerSec: base.uploadedBytesPerSec,
  stage: base.perStageMs.heatmapUpload,
};

// Normalisation choice (column-max vs global) spike visibility.
out.normalisation = ["colMax", "global"].map((norm) => {
  const s = new SceneC({ norm, trailMs: 60_000, mode: "linear" });
  s.init();
  const vals = [];
  for (let r = 0; r < 512; r += 1) vals.push(s.fine.texel(s.fine.count - 1, r) & 0x7fff);
  vals.sort((x, y) => x - y);
  const half = (h) => {
    const e = (h >> 10) & 31,
      m = h & 1023;
    return e === 0 ? 0 : 2 ** (e - 15) * (1 + m / 1024);
  };
  return {
    norm,
    mode: "linear",
    peak: half(vals[511]),
    medianRow: half(vals[256]),
    p90Row: half(vals[460]),
  };
});

// Price-origin shift: shift frame + the amortised coarse tail.
{
  const s = new SceneC({ trailMs: 3600_000 });
  s.init();
  const ev = { kind: "heatmapStream" };
  s.step(0, ev);
  const f0 = s.fine.uploadedBytes,
    c0 = s.coarse.uploadedBytes;
  s.forceJumpRows = 40;
  s.step(100, ev);
  const shiftFrame = s.stats();
  const shiftFrameBytes = s.fine.uploadedBytes - f0 + (s.coarse.uploadedBytes - c0);
  let worst = shiftFrame.frameTimeMs,
    t = 100;
  while (s.pendingCoarseShift !== 0) {
    t += 100;
    s.step(t, ev);
    worst = Math.max(worst, s.stats().frameTimeMs);
  }
  out.originShift = {
    rowsShifted: 40,
    shiftFrameUploadedBytes: shiftFrameBytes,
    expectedFrameBytes: 40 * 2048 * 2 + 4 * 14400 * 2 + 1024, // fine shift + 4 coarse rows + column
    totalShiftBytes: s.c.shiftBytes,
    expectedTotalBytes: 40 * (2048 + 14400) * 2,
    rowsReuploaded: s.c.rowsReuploaded,
    fullTextureBytes: s.fine.bytes + s.coarse.bytes,
    shiftFrameMs: shiftFrame.frameTimeMs,
    worstFrameDuringAmortisationMs: worst,
    ticksToDrain: (t - 100) / 100,
  };
}
// LUT swap.
{
  const s = new SceneC({ trailMs: 60_000 });
  s.init();
  const before = s.fine.uploadedBytes + s.coarse.uploadedBytes;
  out.lutSwap = {
    ...s.swapConvention(),
    heatmapBytesChanged: s.fine.uploadedBytes + s.coarse.uploadedBytes - before,
  };
}
// Capability gaps.
out.capabilityProfiles = Object.fromEntries(
  [
    ["full", {}],
    ["noFloatLinear", { OES_texture_float_linear: false }],
    ["noColorBufferFloat", { EXT_color_buffer_float: false }],
    ["noR16f", { r16fSampling: false }],
    ["noWebgl2", { webgl2: false }],
  ].map(([k, d]) => [k, new SceneC({ caps: { ...FULL_CAPS, ...d }, trailMs: 1000 }).profile]),
);
out.capabilityProbeThisRun = {
  ...FULL_CAPS,
  _note:
    "NOT probed: Node has no WebGL; assumed-full placeholder, must be captured per runtime in a browser",
};

// B10 soak on a simulated clock (60 Hz frames, 10 Hz columns) + mid-soak context loss.
{
  const s = new SceneC({ trailMs: 4 * 3600_000 });
  s.init();
  const total = soakMin * 60_000;
  const events = buildDriverScript({ scenario: "B4", durationMs: total, sampleHz: 60 });
  let outliers = 0,
    frames = 0,
    peak = 0,
    ctx = null,
    sumMs = 0;
  const memSamples = [];
  let nextSample = 0;
  const dropAt = Math.floor(total / 2);
  for (const e of events) {
    if (ctx === null && e.tMs >= dropAt) ctx = s.loseContext();
    s.step(e.tMs, e);
    const f = s.stats().frameTimeMs;
    frames += 1;
    sumMs += f;
    if (f > 33) outliers += 1;
    peak = Math.max(peak, f);
    if (e.tMs >= nextSample) {
      memSamples.push({
        tMin: +(e.tMs / 60000).toFixed(1),
        rssMB: rss(),
        heapMB: Math.round(process.memoryUsage().heapUsed / 1048576),
      });
      nextSample += 60_000;
    }
  }
  const first = memSamples.slice(0, 5).map((m) => m.rssMB),
    last = memSamples.slice(-5).map((m) => m.rssMB);
  const avg = (a) => a.reduce((x, y) => x + y, 0) / a.length;
  out.soak = {
    simulatedMinutes: soakMin,
    frames,
    outliersOver33ms: outliers,
    peakFrameMs: peak,
    meanFrameMs: sumMs / frames,
    peakRssMB: Math.max(...memSamples.map((m) => m.rssMB)),
    rssFirst5AvgMB: avg(first),
    rssLast5AvgMB: avg(last),
    rssGrowthMB: avg(last) - avg(first),
    contextLossRecovery: ctx,
    ext: s.extendedStats(),
    memSamples,
    note: "frame times are cost-model values on a simulated clock; memory is real RSS of this Node process",
  };
}
writeFileSync(join(__dirname, "report-B4-B10.json"), JSON.stringify(out, null, 2) + "\n", "utf8");
console.log(
  JSON.stringify(
    { ...out, soak: { ...out.soak, memSamples: `${out.soak.memSamples.length} samples` } },
    null,
    1,
  ),
);
