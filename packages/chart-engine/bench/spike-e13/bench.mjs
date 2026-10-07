// E13-K01 SPIKE — benchmark harness (throwaway). Run: node --expose-gc bench/spike-e13/bench.mjs
// Runs in a worker_threads Worker (the engine's indicator runtime is worker-hosted) and reports
// full compute, incremental per-closed-bar, worker CPU and memory delta. Not run under coverage.
import { Worker, isMainThread, parentPort } from "node:worker_threads";
import { KERNELS, densify } from "./kernels.mjs";
import { syntheticBars } from "./data.mjs";

const SIZES = [1_000, 10_000, 100_000];
const REPS = 7;
const median = (a) => { const s = [...a].sort((x, y) => x - y); return s[s.length >> 1]; };

function full(K, bars) { const k = new K(bars.length); for (let i = 0; i < bars.length; i += 1) k.push(bars[i]); return k; }

function run() {
  const rows = [];
  const all = densify(syntheticBars(100_000));
  for (const n of SIZES) {
    const bars = all.slice(0, n);
    for (const [name, K] of Object.entries(KERNELS)) {
      full(K, bars); // warm JIT
      const fulls = []; const incs = [];
      for (let r = 0; r < REPS; r += 1) {
        const c0 = process.cpuUsage(); const t0 = performance.now(); full(K, bars); const t1 = performance.now();
        fulls.push({ ms: t1 - t0, cpu: (process.cpuUsage(c0).user + process.cpuUsage(c0).system) / 1000 });
        // incremental: prime n-1000 bars, then time each of the last 1000 closed-bar pushes
        const m = Math.max(0, n - 1000); const k = new K(n); for (let i = 0; i < m; i += 1) k.push(bars[i]);
        const s0 = performance.now(); for (let i = m; i < n; i += 1) k.push(bars[i]); incs.push(((performance.now() - s0) * 1000) / (n - m));
      }
      rows.push({ indicator: name, bars: n, full_ms_median: median(fulls.map((x) => x.ms)), full_ms_min: Math.min(...fulls.map((x) => x.ms)), cpu_ms_median: median(fulls.map((x) => x.cpu)), incr_us_per_bar_median: median(incs) });
    }
  }
  // Memory: ten active indicators at 100k bars (SMA x3, MACD x2, Ichimoku x2, VWAP x3), gc before/after.
  globalThis.gc?.(); const m0 = process.memoryUsage();
  const live = []; const mix = ["sma", "sma", "sma", "macd", "macd", "ichimoku", "ichimoku", "vwap", "vwap", "vwap"];
  const c0 = process.cpuUsage(); const t0 = performance.now();
  for (const name of mix) live.push(full(KERNELS[name], all));
  const tenMs = performance.now() - t0; const tenCpu = (process.cpuUsage(c0).user + process.cpuUsage(c0).system) / 1000;
  const s0 = performance.now(); const extra = { t: all.at(-1).t + 60_000, o: 1, h: 1, l: 1, c: 1, v: 1 };
  for (let r = 0; r < 1000; r += 1) for (const k of live) { k.i -= 1; k.push(extra); }
  const tenInc = ((performance.now() - s0) * 1000) / 1000;
  globalThis.gc?.(); const m1 = process.memoryUsage();
  const mb = (x) => x / 1048576;
  return { rows, ten: { bars: all.length, full_ms: tenMs, cpu_ms: tenCpu, incr_us_per_closed_bar_all_ten: tenInc, heap_delta_mb: mb(m1.heapUsed - m0.heapUsed), arraybuffers_delta_mb: mb(m1.arrayBuffers - m0.arrayBuffers), live: live.length } };
}

if (isMainThread) {
  const w = new Worker(new URL(import.meta.url));
  w.on("message", (r) => { console.log(JSON.stringify(r, null, 1)); });
  w.on("error", (e) => { console.error(e); process.exitCode = 1; });
} else {
  parentPort.postMessage(run());
}
