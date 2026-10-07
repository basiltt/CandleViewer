// E13-K01 SPIKE — THROWAWAY prototype worker kernels (not production; see
// docs/plan/notes/e13-k01-indicator-compute.md). No DOM, no React, no network
// (.claude/rules/31-chart-engine.md). Plain ESM like the rest of bench/ (Node 20
// cannot run .ts without a loader; the arithmetic is identical under TS).
// Every kernel is a streaming recurrence: full compute = push() over all bars,
// incremental = one push() per closed bar. Outputs are Float64Array (NaN = warm-up).

export class Sma {
  constructor(cap, n = 20) { this.n = n; this.out = new Float64Array(cap); this.ring = new Float64Array(n); this.sum = 0; this.i = 0; }
  push(b) {
    const k = this.i % this.n;
    if (this.i >= this.n) this.sum -= this.ring[k];
    this.ring[k] = b.c; this.sum += b.c;
    this.out[this.i] = this.i >= this.n - 1 ? this.sum / this.n : NaN;
    this.i += 1;
  }
}

// EMA seeded with the SMA of the first n values (TA-Lib convention).
class Ema {
  constructor(n) { this.n = n; this.a = 2 / (n + 1); this.k = 0; this.acc = 0; this.v = NaN; }
  push(x) {
    if (this.k < this.n) { this.acc += x; this.k += 1; if (this.k === this.n) this.v = this.acc / this.n; return this.v; }
    this.v = (x - this.v) * this.a + this.v; return this.v;
  }
}

// MACD(12,26,9) on a densified series (synthetic flat bars carry prev close).
export class Macd {
  constructor(cap, f = 12, s = 26, sig = 9) {
    this.ef = new Ema(f); this.es = new Ema(s); this.eg = new Ema(sig);
    this.macd = new Float64Array(cap); this.signal = new Float64Array(cap); this.hist = new Float64Array(cap); this.i = 0;
  }
  push(b) {
    const f = this.ef.push(b.c); const s = this.es.push(b.c);
    const m = Number.isNaN(s) ? NaN : f - s;
    const g = Number.isNaN(m) ? NaN : this.eg.push(m);
    this.macd[this.i] = m; this.signal[this.i] = g; this.hist[this.i] = Number.isNaN(g) ? NaN : m - g;
    this.i += 1;
  }
}

// Monotonic deque rolling max/min over window w (amortised O(1) per push).
class RollExt {
  constructor(cap, w, isMax) { this.w = w; this.isMax = isMax; this.idx = new Int32Array(cap); this.val = new Float64Array(cap); this.h = 0; this.t = 0; }
  push(i, x) {
    while (this.t > this.h && (this.isMax ? this.val[this.t - 1] <= x : this.val[this.t - 1] >= x)) this.t -= 1;
    this.idx[this.t] = i; this.val[this.t] = x; this.t += 1;
    while (this.idx[this.h] <= i - this.w) this.h += 1;
    return this.val[this.h];
  }
}

// Ichimoku(9,26,52). Senkou spans are stored at their *source* index; the renderer
// shifts them +26 (display offset is a layout concern, not a compute one).
export class Ichimoku {
  constructor(cap, t = 9, k = 26, sb = 52) {
    this.t = t; this.k = k; this.sb = sb; this.i = 0;
    this.hT = new RollExt(cap, t, true); this.lT = new RollExt(cap, t, false);
    this.hK = new RollExt(cap, k, true); this.lK = new RollExt(cap, k, false);
    this.hS = new RollExt(cap, sb, true); this.lS = new RollExt(cap, sb, false);
    this.tenkan = new Float64Array(cap); this.kijun = new Float64Array(cap);
    this.spanA = new Float64Array(cap); this.spanB = new Float64Array(cap); this.chikou = new Float64Array(cap);
  }
  push(b) {
    const i = this.i;
    const ht = this.hT.push(i, b.h), lt = this.lT.push(i, b.l);
    const hk = this.hK.push(i, b.h), lk = this.lK.push(i, b.l);
    const hs = this.hS.push(i, b.h), ls = this.lS.push(i, b.l);
    const tk = i >= this.t - 1 ? (ht + lt) / 2 : NaN;
    const kj = i >= this.k - 1 ? (hk + lk) / 2 : NaN;
    this.tenkan[i] = tk; this.kijun[i] = kj;
    this.spanA[i] = Number.isNaN(kj) ? NaN : (tk + kj) / 2;
    this.spanB[i] = i >= this.sb - 1 ? (hs + ls) / 2 : NaN;
    this.chikou[i] = b.c;
    this.i += 1;
  }
}

// Session VWAP (UTC-day anchor) on typical price with ±1/2/3σ volume-weighted bands.
export class Vwap {
  constructor(cap, dayMs = 86_400_000) {
    this.dayMs = dayMs; this.day = -1; this.sv = 0; this.spv = 0; this.spv2 = 0; this.i = 0;
    this.vwap = new Float64Array(cap); this.sd = new Float64Array(cap);
    this.bands = Array.from({ length: 6 }, () => new Float64Array(cap)); // +1,-1,+2,-2,+3,-3
  }
  push(b) {
    const d = Math.floor(b.t / this.dayMs);
    if (d !== this.day) { this.day = d; this.sv = 0; this.spv = 0; this.spv2 = 0; }
    const tp = (b.h + b.l + b.c) / 3;
    this.sv += b.v; this.spv += tp * b.v; this.spv2 += tp * tp * b.v;
    const i = this.i;
    if (this.sv > 0) {
      const m = this.spv / this.sv; const varr = this.spv2 / this.sv - m * m;
      const s = varr > 0 ? Math.sqrt(varr) : 0;
      this.vwap[i] = m; this.sd[i] = s;
      for (let k = 1; k <= 3; k += 1) { this.bands[2 * k - 2][i] = m + k * s; this.bands[2 * k - 1][i] = m - k * s; }
    } else {
      this.vwap[i] = NaN; this.sd[i] = NaN; for (const a of this.bands) a[i] = NaN;
    }
    this.i += 1;
  }
}

/** Output arrays per kernel, for parity dumps and memory accounting. */
export function outputs(k) {
  if (k instanceof Sma) return { sma: k.out };
  if (k instanceof Macd) return { macd: k.macd, signal: k.signal, hist: k.hist };
  if (k instanceof Ichimoku) return { tenkan: k.tenkan, kijun: k.kijun, spanA: k.spanA, spanB: k.spanB, chikou: k.chikou };
  return { vwap: k.vwap, sd: k.sd, up1: k.bands[0], dn1: k.bands[1], up2: k.bands[2], dn2: k.bands[3], up3: k.bands[4], dn3: k.bands[5] };
}

export const KERNELS = { sma: Sma, macd: Macd, ichimoku: Ichimoku, vwap: Vwap };

/** BarSeries.densify(): flat synthetic bars for empty 1m intervals (24-internal-schemas §5). */
export function densify(bars, stepMs = 60_000) {
  const out = [];
  for (const b of bars) {
    const prev = out[out.length - 1];
    if (prev) for (let t = prev.t + stepMs; t < b.t; t += stepMs) out.push({ t, o: prev.c, h: prev.c, l: prev.c, c: prev.c, v: 0, synthetic: true });
    out.push(b);
  }
  return out;
}
