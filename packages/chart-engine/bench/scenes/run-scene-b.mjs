#!/usr/bin/env node
// THROWAWAY PROTOTYPE (E06-K03) CLI: B3 for the SDF arm and the Canvas-2D
// spot-check arm, atlas cold/cached timing, outline cost, reformat cost, LOD
// sweep. `node ./bench/scenes/run-scene-b.mjs --reps=3 --durationMs=20000`
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { SceneB } from "./scene-b.mjs";
import { runScenario } from "../runner.mjs";
import { captureMachineDescriptor } from "../machine.mjs";
import { generateM0Fixture } from "../fixtures/index.mjs";
import { toSeed32 } from "../fixtures/rng.mjs";
import { loadAtlas, MemoryAtlasStore, contrastRatio } from "./atlas.mjs";
import { selectFootprintLod } from "./footprint-lod.mjs";

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
const seed = toSeed32(args.seed ?? "20260928");
const fixture = generateM0Fixture({ seed, barCount: 200 });

function runArm(arm, outline, volumeScale) {
  const scene = new SceneB({ arm, outline, volumeScale });
  scene.init(fixture);
  const report = runScenario({
    scene,
    scenario: "B3",
    durationMs,
    repetitions: reps,
    runtime: "chromium",
    runtimeVersion: `node-${process.version}`,
    machine: captureMachineDescriptor({ gpu: "none (headless Node)", driver: "modelled-cost" }),
    seed,
    lodProfile: "LOD_PROFILE_M0",
    peakProcessMemMB: Math.round(process.memoryUsage().rss / 1048576),
    peakProcessMemSource: "process.memoryUsage().rss",
  });
  const ext = scene.extendedStats();
  scene.dispose();
  return { report, ext };
}

const sdf = runArm("sdf", true);
const sdfNoOutline = runArm("sdf", false);
const c2d = runArm("canvas2d", true);
const sdfStress = runArm("sdf", true, 60); // 5-digit values, ~2x glyph load

const store = new MemoryAtlasStore();
const cold = await loadAtlas(store, "Inter", 500);
const warm = await loadAtlas(store, "Inter", 500);

const s = new SceneB();
s.init(fixture);
const reformatMs = s.setFormat("compact");

const contrast = {
  fgVsOutline: contrastRatio("#E8EAED", "#0B0E11"),
  hcFgVsOutline: contrastRatio("#F6F8FA", "#0B0E11"),
  rawBid: contrastRatio("#E8EAED", "#2EBD59"),
  rawAsk: contrastRatio("#E8EAED", "#E5484D"),
};

let prev = null;
let changes = 0;
const sweep = (h) => {
  const n = selectFootprintLod(h, prev);
  if (prev && n !== prev) changes += 1;
  prev = n;
};
for (let h = 16; h >= 4; h -= 0.05) sweep(h);
for (let h = 4; h <= 16; h += 0.05) sweep(h);

const out = {
  machine: sdf.report.machine,
  b3: {
    sdf: {
      p95: sdf.report.p95,
      drawCalls: sdf.report.drawCalls,
      textureMemMB: sdf.report.textureMemMB,
      ...sdf.ext,
    },
    sdfStress5Digit: { p95: sdfStress.report.p95, ...sdfStress.ext },
    sdfNoOutline: { p95: sdfNoOutline.report.p95, ...sdfNoOutline.ext },
    canvas2d: {
      p95: c2d.report.p95,
      drawCalls: c2d.report.drawCalls,
      textureMemMB: c2d.report.textureMemMB,
      ...c2d.ext,
    },
  },
  atlas: {
    coldMs: cold.ms,
    genMs: cold.atlas.genMs,
    cachedMs: warm.ms,
    cacheHit: warm.cacheHit,
    orderHash: cold.atlas.orderHash,
    usedHeight: cold.atlas.usedHeight,
    bytes: cold.atlas.size * cold.atlas.size,
  },
  reformatMs,
  contrast,
  lodSweepChangesRoundTrip: changes,
};
writeFileSync(join(__dirname, "report-B3.json"), JSON.stringify(out, null, 2) + "\n", "utf8");
console.log(JSON.stringify(out, null, 1));
