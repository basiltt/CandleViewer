// E06-T01 matrix page: runs inside Chromium / Electron renderer / WebView2.
// Driven entirely by URL query params and reports to the runner's HTTP server
// (POST /result, POST /done), so the SAME page + script serves all three runtimes
// (ticket: "same seed, fixture and driver script"). No Node APIs, no network
// beyond the loopback harness server (which rewrites `node:*` imports to shims).
import { generateM0Fixture } from "../../fixtures/index.mjs";
import { toSeed32, mulberry32 } from "../../fixtures/rng.mjs";
import { buildDriverScript } from "../../driver.mjs";
import { percentile } from "../../stats.mjs";
import { SceneA } from "../../scenes/scene-a.mjs";
import { SceneB } from "../../scenes/scene-b.mjs";
import { SceneC } from "../../scenes/scene-c.mjs";
import { SceneB5, B5_GATES } from "../scenes/b5-combined.mjs";
import { STORM, encodeMessage, evaluateStorm, runStormInline } from "../scenes/b7-storm.mjs";
import { fixtureDigests } from "../fixture-digest.mjs";
import { GlLoad, probeCapabilities } from "./gl-load.mjs";
import { summariseFrames, soakBuckets } from "../frame-stats.mjs";

const q = new URLSearchParams(location.search);
const cfg = {
  scenarios: (q.get("scenarios") ?? "B1,B2,B3,B4,B5,B7,B9,B10").split(","),
  reps: Number(q.get("reps") ?? 3),
  seed: q.get("seed") ?? "20260928",
  barCount: Number(q.get("barCount") ?? 100_000),
  durationMs: Number(q.get("durationMs") ?? 20_000),
  soakMs: Number(q.get("soakMs") ?? 30 * 60_000),
  warmupFrames: Number(q.get("warmup") ?? 60),
};
const statusEl = document.getElementById("status");
const say = (s) => {
  statusEl.textContent = s;
};
const post = (path, body) =>
  fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });

const mirror = document.getElementById("mirror");
for (let i = 0; i < 100; i += 1) mirror.appendChild(document.createElement("li"));
let mirrorTick = 0;
/** DOM-mirror stage (E06-D03): rewrite 100 text nodes per frame, timed. */
function domMirrorSync() {
  const t0 = performance.now();
  mirrorTick += 1;
  for (let i = 0; i < mirror.children.length; i += 1) {
    mirror.children[i].textContent = `row ${i} v ${(mirrorTick * 31 + i) % 997}`;
  }
  return performance.now() - t0;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const nextFrame = () => new Promise((r) => requestAnimationFrame(() => r(0)));

function makeScene(scenario, fixture, seed32) {
  let scene;
  if (scenario === "B3") scene = new SceneB();
  else if (scenario === "B4") scene = new SceneC({ seed: seed32 });
  else if (scenario === "B5") scene = new SceneB5({ seed: seed32 });
  else scene = new SceneA(); // B1, B2, B9, B10 (B10 adds scene C below)
  scene.init(fixture);
  let heat = null;
  if (scenario === "B10") {
    heat = new SceneC({ seed: seed32 });
    heat.init();
  }
  return { scene, heat };
}

/** One repetition of a frame-driven scenario with REAL GL work + DOM mirror. */
async function runRep(scenario, fixture, seed32, gl, durationMs, paced) {
  const { scene, heat } = makeScene(scenario, fixture, seed32);
  const script = buildDriverScript({ scenario, durationMs, sampleHz: 60 });
  if (scenario === "B10") {
    // driver.mjs B10 is pan-only; ADR-0011 criteria 2/3 need the 10 Hz heatmap stream.
    for (let t = 0; t < durationMs; t += 100) {
      script.push({ tMs: t, kind: "heatmapStream", payload: {} });
    }
    script.sort((a, b) => a.tMs - b.tMs);
  }
  const frameMs = [];
  const frameAt = [];
  const uploadMs = [];
  const uploadAt = [];
  const mirrorMs = [];
  let drawCalls = 0;
  let warm = cfg.warmupFrames;
  const start = performance.now();
  for (const ev of script) {
    if (paced) {
      const wait = start + ev.tMs - performance.now();
      if (wait > 4) await sleep(wait - 2);
    }
    const f0 = performance.now();
    scene.step(ev.tMs, ev);
    if (heat && ev.kind === "heatmapStream") heat.step(ev.tMs, ev);
    drawCalls = scene.stats().drawCalls + (heat ? heat.stats().drawCalls : 0);
    const up = ev.kind === "heatmapStream" ? gl.uploadColumn() : 0;
    gl.draw(Math.max(1, drawCalls), ev.tMs / 1000);
    const m = domMirrorSync();
    const total = performance.now() - f0;
    if (warm > 0) {
      warm -= 1;
      continue;
    }
    frameMs.push(total);
    frameAt.push(ev.tMs);
    mirrorMs.push(m);
    if (ev.kind === "heatmapStream") {
      uploadMs.push(up);
      uploadAt.push(ev.tMs);
    }
  }
  const out = { ...summariseFrames(frameMs), drawCalls, frames: frameMs.length };
  out.mirrorP95Ms = percentile(mirrorMs, 95);
  out.modelledStageMs = scene.stats().perStageMs;
  if (uploadMs.length) out.texUploadMedianMs = percentile(uploadMs, 50);
  if (scenario === "B10") out.soak = soakBuckets(frameAt, frameMs, uploadAt, uploadMs, 60_000);
  if (scenario === "B5") out.composition = scene.describe();
  scene.dispose();
  heat?.dispose();
  return out;
}

function runCold(fixture, gl) {
  const t0 = performance.now();
  const s = new SceneA();
  s.init(fixture);
  s.step(0, { tMs: 0, kind: "none" });
  gl.draw(4, 0);
  const ms = performance.now() - t0;
  s.dispose();
  return { coldInitToFirstFrameMs: ms };
}

async function runStormWorker(seed32, durationMs) {
  const w = new Worker(new URL("./storm-worker.mjs", import.meta.url), { type: "module" });
  let off = null;
  try {
    off = document.createElement("canvas").transferControlToOffscreen();
  } catch {
    off = null;
  }
  const ready = await new Promise((resolve) => {
    w.onmessage = (e) => e.data.type === "ready" && resolve(e.data);
    w.postMessage({ type: "init", canvas: off }, off ? [off] : []);
  });
  const rng = mulberry32(seed32 ^ 0xb7);
  const period = 1000 / STORM.msgsPerSecPerStore;
  const total = Math.floor(durationMs / period);
  const seqs = new Int32Array(STORM.storeCount);
  const t0 = performance.now();
  for (let tick = 0; tick < total; tick += 1) {
    const wait = t0 + tick * period - performance.now();
    if (wait > 0) await sleep(wait);
    for (let s = 0; s < STORM.storeCount; s += 1) {
      const buf = encodeMessage(rng, s, seqs[s]++);
      w.postMessage({ type: "msg", buf }, [buf]);
    }
  }
  const result = await new Promise((resolve) => {
    w.onmessage = (e) => e.data.type === "result" && resolve(e.data);
    w.postMessage({ type: "done" });
  });
  w.terminate();
  return { ...result, offscreenWebgl2InWorker: ready.offscreenWebgl2 };
}

async function runStorm(seed32) {
  const storm = {};
  const dur = Math.min(cfg.durationMs, 10_000);
  for (let r = 0; r < cfg.reps; r += 1) {
    const inl = await runStormInline({
      durationMs: dur,
      seed: seed32 + r,
      now: () => performance.now(),
      sleep,
    });
    (storm.inline ??= []).push(evaluateStorm(inl, percentile));
    try {
      const wk = await runStormWorker(seed32 + r, dur);
      (storm.worker ??= []).push({
        ...evaluateStorm(wk, percentile),
        offscreenWebgl2InWorker: wk.offscreenWebgl2InWorker,
        workerFrameP95Ms: percentile(wk.frameMs, 95),
      });
    } catch (e) {
      storm.workerError = String(e);
    }
  }
  return storm;
}

async function runCell(scenario, fixture, seed32, gl) {
  /** @type {any} */
  const cell = { kind: "cell", scenario, reps: [] };
  try {
    if (scenario === "B7") {
      cell.storm = await runStorm(seed32);
    } else if (!gl) {
      cell.notRunnable = "WebGL2 unavailable (ADR-0011 criterion 4 gap); not averaged or omitted";
    } else if (scenario === "B9") {
      for (let r = 0; r < cfg.reps; r += 1) cell.reps.push(runCold(fixture, gl));
    } else {
      const soak = scenario === "B10";
      const reps = soak ? 1 : cfg.reps; // soak once per runtime (ticket)
      for (let r = 0; r < reps; r += 1) {
        const ms = soak ? cfg.soakMs : cfg.durationMs;
        cell.reps.push(await runRep(scenario, fixture, seed32, gl, ms, soak));
        await nextFrame();
      }
    }
  } catch (e) {
    cell.notRunnable = `exception: ${e && e.stack ? e.stack : e}`;
  }
  return cell;
}

async function main() {
  const seed32 = toSeed32(cfg.seed);
  say("capability probe");
  const caps = probeCapabilities();
  say(`generating fixture (${cfg.barCount} bars) - slow by design, ~15-40 s`);
  const fixture = generateM0Fixture({ seed: cfg.seed, barCount: cfg.barCount });
  say("hashing fixture");
  const digests = await fixtureDigests(fixture);
  await post("/result", {
    kind: "preamble",
    userAgent: navigator.userAgent,
    caps,
    fixture: { seed: cfg.seed, seed32, barCount: cfg.barCount, ...digests },
    cfg,
    b5Gates: B5_GATES,
  });
  let gl = null;
  try {
    gl = new GlLoad(document.getElementById("c"));
  } catch (e) {
    await post("/result", { kind: "gl-unavailable", error: String(e) });
  }
  for (const scenario of cfg.scenarios) {
    say(`running ${scenario}`);
    await post("/result", await runCell(scenario, fixture, seed32, gl));
  }
  gl?.dispose();
  say("done");
  await post("/done", {});
}

main().catch(async (e) => {
  say(`FAILED ${e}`);
  await post("/done", { error: String(e && e.stack ? e.stack : e) });
});
