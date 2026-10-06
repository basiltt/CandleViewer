/* global process, console, performance, atob, TextDecoder, navigator */
// E17-K01 browser decode harness (THROWAWAY). Runs in headless Chromium via playwright-core,
// reusing the chart-engine bench runner's pinned engine (bench/report.mjs PINNED_CHROMIUM_FLAGS
// stay for GPU scenes; decode is CPU-only so only the browser binary + machine descriptor are
// shared) and its percentile/median helpers (bench/stats.mjs, bench/machine.mjs).
//
//   node tests/perf/ws/run_browser.mjs [--runs=5] [--out=tests/perf/ws/out/browser-results.json]
//
// Timed region = the decode function ONLY (performance.now around decode, no rendering, no
// checksum). Equivalence (checksum vs the Python canonical flat) is checked outside the timer.
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { homedir } from "node:os";
import { captureMachineDescriptor } from "../../../packages/chart-engine/bench/machine.mjs";
import { percentile } from "../../../packages/chart-engine/bench/stats.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, "").split("=")));
const RUNS = Number(args.runs ?? 5);
const OUT = resolve(args.out ?? join(here, "out", "browser-results.json"));

const require = createRequire(import.meta.url);
const pwPath = join(
  here,
  "../../../node_modules/.pnpm/playwright-core@1.63.0/node_modules/playwright-core",
);
const { chromium } = require(pwPath);
const shell = join(
  homedir(),
  "AppData/Local/ms-playwright/chromium_headless_shell-1243",
  "chrome-headless-shell-win64/chrome-headless-shell.exe",
);
if (!existsSync(shell)) throw new Error(`headless chromium not found: ${shell}`);

const frames = JSON.parse(readFileSync(join(here, "out/browser-frames.json"), "utf8"));
const w2 = {
  scaled: JSON.parse(readFileSync(join(here, "out/browser-w2-scaled.json"), "utf8")),
  constant: JSON.parse(readFileSync(join(here, "out/browser-w2-constant.json"), "utf8")),
};
const msgpackSrc = readFileSync(join(here, "vendor/msgpack-3.1.3.umd.min.txt"), "utf8");

// Everything below the marker is serialised into the page.
function pageMain(payload) {
  const { frames, w2, runs } = payload;
  const MP = globalThis.MessagePack;
  const M = 1000003;
  const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  const text = new TextDecoder();

  // ---- decoders (the timed functions) --------------------------------------------------
  const decJson = (s) => JSON.parse(s); // WS text frame arrives as a string
  const decMp = (u8) => MP.decode(u8);
  // binary: msgpack envelope (bin payload is a subarray view) + body header + SoA decode.
  const u64 = (dv, o) => dv.getUint32(o, true) + dv.getUint32(o + 4, true) * 4294967296;
  const i64 = (dv, o) => dv.getUint32(o, true) + dv.getInt32(o + 4, true) * 4294967296;
  function decBinBody(body) {
    const dv = new DataView(body.buffer, body.byteOffset, body.byteLength);
    if (dv.getUint32(0, true) !== 0x43565742 || dv.getUint8(4) !== 1) throw new Error("magic");
    const kind = dv.getUint8(5);
    const count = dv.getUint32(12, true);
    const base = u64(dv, 16);
    let o = 24;
    if (kind === 1 || kind === 2) {
      const side = new Uint8Array(count),
        px = new Float64Array(count),
        qty = new Float64Array(count);
      for (let i = 0; i < count; i++, o += 17) {
        side[i] = dv.getUint8(o);
        px[i] = i64(dv, o + 1);
        qty[i] = u64(dv, o + 9);
      }
      return { kind, count, side, px, qty };
    }
    if (kind === 3) {
      const ts = new Float64Array(count),
        px = new Float64Array(count),
        qty = new Float64Array(count);
      const side = new Uint8Array(count),
        fl = new Uint8Array(count);
      for (let i = 0; i < count; i++, o += 22) {
        ts[i] = base + dv.getUint32(o, true);
        px[i] = i64(dv, o + 4);
        qty[i] = u64(dv, o + 12);
        side[i] = dv.getUint8(o + 20);
        fl[i] = dv.getUint8(o + 21);
      }
      return { kind, count, ts, px, qty, side, fl };
    }
    if (kind === 4) {
      const f = new Float64Array(count * 10);
      for (let i = 0; i < count; i++, o += 65) {
        const k = i * 10;
        f[k] = base + dv.getUint32(o, true);
        for (let j = 0; j < 4; j++) f[k + 1 + j] = i64(dv, o + 4 + 8 * j);
        f[k + 5] = u64(dv, o + 36);
        f[k + 6] = u64(dv, o + 44);
        f[k + 7] = dv.getUint32(o + 52, true);
        f[k + 8] = i64(dv, o + 56);
        f[k + 9] = dv.getUint8(o + 64);
      }
      return { kind, count, f };
    }
    if (kind === 5) {
      const t = base + dv.getUint32(o, true);
      const n = dv.getUint32(o + 4, true);
      o += 8;
      const px = new Float64Array(n),
        bid = new Float64Array(n),
        ask = new Float64Array(n);
      const trd = new Uint32Array(n),
        fl = new Uint8Array(n);
      for (let i = 0; i < n; i++, o += 29) {
        px[i] = i64(dv, o);
        bid[i] = u64(dv, o + 8);
        ask[i] = u64(dv, o + 16);
        trd[i] = dv.getUint32(o + 24, true);
        fl[i] = dv.getUint8(o + 28);
      }
      return { kind, count, t, n, px, bid, ask, trd, fl };
    }
    const t = base + dv.getUint32(o, true);
    const pmin = i64(dv, o + 4);
    const pstep = i64(dv, o + 12);
    const rows = dv.getUint32(o + 20, true);
    o = 24 + 24;
    const bid = new Float64Array(rows),
      ask = new Float64Array(rows);
    for (let i = 0; i < rows; i++, o += 16) {
      bid[i] = u64(dv, o);
      ask[i] = u64(dv, o + 8);
    }
    return { kind, count, t, pmin, pstep, rows, bid, ask };
  }
  const decBin = (u8) => decBinBody(MP.decode(u8).p);

  // ---- canonical flatteners (untimed; equivalence ground truth) -------------------------
  const sc = (s, k) => Math.round(parseFloat(s) * 10 ** k);
  function flatStruct(kind, env) {
    const p = env.p;
    const o = [];
    if (kind.startsWith("book")) {
      o.push(p.bids.length, p.asks.length);
      for (const [a, b] of [...p.bids, ...p.asks]) o.push(sc(a, 1), sc(b, 3));
    } else if (kind === "trades") {
      o.push(p.trades.length);
      for (const t of p.trades)
        o.push(
          t.ts_ms,
          sc(t.price, 1),
          sc(t.size, 3),
          t.side === "buy" ? 0 : 1,
          t.is_block_trade ? 1 : 0,
        );
    } else if (kind === "bars") {
      const b = p.bars[0];
      o.push(
        1,
        b.t_ms,
        sc(b.o, 1),
        sc(b.h, 1),
        sc(b.l, 1),
        sc(b.c, 1),
        sc(b.v, 3),
        sc(b.turnover, 3),
        b.trades,
        sc(b.delta, 3),
        b.confirm ? 1 : 0,
      );
    } else if (kind === "footprint") {
      const b = p.bars[0];
      o.push(1, b.t_ms, b.cells.length);
      for (const c of b.cells)
        o.push(
          sc(c.price, 1),
          sc(c.bid_volume, 3),
          sc(c.ask_volume, 3),
          c.trades,
          c.is_poc ? 8 : 0,
        );
    } else {
      const c = p.columns[0];
      o.push(c.t_ms, sc(c.price_min, 1), sc(c.price_step, 1), c.bids.length);
      for (let i = 0; i < c.bids.length; i++)
        o.push(Math.round(c.bids[i] * 1000), Math.round(c.asks[i] * 1000));
    }
    return o;
  }
  function flatBin(kind, d) {
    const o = [];
    if (d.kind === 1 || d.kind === 2) {
      const b = [],
        a = [];
      for (let i = 0; i < d.count; i++) (d.side[i] === 0 ? b : a).push(d.px[i], d.qty[i]);
      o.push(b.length / 2, a.length / 2, ...b, ...a);
    } else if (d.kind === 3) {
      o.push(d.count);
      for (let i = 0; i < d.count; i++) o.push(d.ts[i], d.px[i], d.qty[i], d.side[i], d.fl[i]);
    } else if (d.kind === 4) {
      o.push(d.count, ...d.f);
    } else if (d.kind === 5) {
      o.push(1, d.t, d.n);
      for (let i = 0; i < d.n; i++) o.push(d.px[i], d.bid[i], d.ask[i], d.trd[i], d.fl[i]);
    } else {
      o.push(d.t, d.pmin, d.pstep, d.rows);
      for (let i = 0; i < d.rows; i++) o.push(d.bid[i], d.ask[i]);
    }
    return o;
  }
  const mod = (v) => ((v % M) + M) % M;
  const checksum = (flat) => {
    let s = 0,
      w = 0;
    for (let i = 0; i < flat.length; i++) {
      const m = mod(flat[i]);
      s += m;
      w += (i + 1) * m;
    }
    return [flat.length, s % M, w % M];
  };
  const same = (a, b) => a[0] === b[0] && a[1] === b[1] && a[2] === b[2];

  // ---- measurement ---------------------------------------------------------------------
  const prep = (arm, b64s) => (arm === "json" ? text.decode(b64(b64s)) : b64(b64s));
  const dec = { json: decJson, msgpack: decMp, binary: decBin };
  const stats = (xs) => {
    const s = [...xs].sort((a, b) => a - b);
    const q = (p) => s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))];
    return { p50: q(50), p95: q(95), p99: q(99), mean: xs.reduce((a, b) => a + b, 0) / xs.length };
  };
  let sink = 0;
  function timeFrame(fn, input) {
    // calibrate repeats so one timed region is >= ~1.5 ms (timer is coarse), result in us
    let r = 1;
    let t0 = performance.now();
    for (let i = 0; i < r; i++) sink += fn(input) ? 1 : 0;
    let dt = performance.now() - t0;
    while (dt < 1.5 && r < 4096) {
      r *= 2;
      t0 = performance.now();
      for (let i = 0; i < r; i++) sink += fn(input) ? 1 : 0;
      dt = performance.now() - t0;
    }
    return (dt / r) * 1000;
  }
  function run(manifest) {
    const res = {};
    for (const [kind, m] of Object.entries(manifest)) {
      res[kind] = {};
      for (const arm of ["json", "msgpack", "binary"]) {
        const inputs = m.arms[arm].map((s) => prep(arm, s));
        // equivalence (untimed)
        inputs.forEach((inp, i) => {
          const d = dec[arm](inp);
          const flat =
            arm === "binary" ? flatBin(kind, d) : flatStruct(kind, arm === "json" ? { p: d.p } : d);
          if (!same(checksum(flat), m.checks[i]))
            throw new Error(`equivalence FAIL ${arm} ${kind} #${i}`);
        });
        for (let w = 0; w < 3; w++) inputs.forEach((inp) => dec[arm](inp)); // JIT warmup
        const per = inputs.map((inp) => timeFrame(dec[arm], inp));
        res[kind][arm] = {
          ...stats(per),
          frames: per.length,
          bytes: arm === "json" ? inputs[0].length : inputs[0].length,
        };
      }
    }
    return res;
  }
  const out = { runs: [], w2: { scaled: [], constant: [] } };
  for (let r = 0; r < runs; r++) out.runs.push(run(frames));
  for (const mode of ["scaled", "constant"]) {
    for (let r = 0; r < runs; r++) out.w2[mode].push(run(w2[mode]));
  }
  out.sink = sink;
  out.userAgent = navigator.userAgent;
  return out;
}

const browser = await chromium.launch({
  executablePath: shell,
  args: [
    "--js-flags=--no-opt-bailout-noise",
    "--disable-gpu",
    "--disable-background-timer-throttling",
  ],
});
const version = browser.version();
const page = await browser.newPage();
await page.goto("about:blank");
await page.addScriptTag({ content: msgpackSrc });
// W2 manifests have no "kind" - key by depth name but flatten as book_delta.
const w2k = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v]));
const raw = await page
  .evaluate(
    ({ src, payload }) => {
      const fn = new Function("payload", `return (${src})(payload)`);
      return fn(payload);
    },
    {
      src: pageMain.toString(),
      payload: { frames, w2: { scaled: w2k(w2.scaled), constant: w2k(w2.constant) }, runs: RUNS },
    },
  )
  .catch(async (e) => {
    await browser.close();
    throw e;
  });
await browser.close();

const med = (xs) => percentile(xs, 50);
function summarise(runs) {
  const out = {};
  for (const kind of Object.keys(runs[0])) {
    out[kind] = {};
    for (const arm of Object.keys(runs[0][kind])) {
      const col = (k) => runs.map((r) => r[kind][arm][k]);
      out[kind][arm] = {
        p50_us: med(col("p50")),
        p95_us: med(col("p95")),
        p99_us: med(col("p99")),
        mean_us: med(col("mean")),
        p50_runs_us: col("p50"),
      };
    }
  }
  return out;
}
const machine = captureMachineDescriptor({ gpu: "n/a (CPU-only decode)", driver: "n/a" });
const result = {
  harness: "E17-K01 browser decode",
  runs: RUNS,
  browser: version,
  engine: "chrome-headless-shell (Playwright chromium_headless_shell-1243), V8",
  msgpack_lib: "@msgpack/msgpack 3.1.3 (UMD, vendored, ISC)",
  node: process.version,
  machine,
  four_pane: summarise(raw.runs),
  w2_scaled: summarise(raw.w2.scaled),
  w2_constant: summarise(raw.w2.constant),
};
writeFileSync(OUT, JSON.stringify(result, null, 1));
console.log("wrote", OUT, "browser", version);
