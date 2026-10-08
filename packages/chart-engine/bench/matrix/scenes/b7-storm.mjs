// E06-T01 — B7 "live update storm" (docs/plan/26-chart-engine-design.md §13).
// 20 data messages/s x 6 stores (= 120 msg/s aggregate). Gates: decode p95 <= 4 ms,
// ZERO dropped messages (every sent sequence number must be applied exactly once,
// in per-store order) and frame time <= 16.7 ms.
//
// Two execution modes, labelled and NEVER averaged together (ticket Technical notes):
//   "worker"  decode + apply in a Worker, rendering to an OffscreenCanvas (design §2).
//   "inline"  the same decode/apply code on the main thread = `RunMode.inline`, the
//             supported fallback for WebViews lacking OffscreenCanvas-in-worker.
// The decode/apply code below is shared by both modes (one implementation, as the
// design requires: "only throughput changes, not behaviour").
//
// Wire format (columnar, little-endian), header 16 B then struct-of-arrays:
//   u32 magic 0x43564231 | u32 storeId | u32 seq | u32 rows
//   f64[rows] time | f32[rows] price | f32[rows] qty | u8[rows] side
import { mulberry32 } from "../../fixtures/rng.mjs";

export const STORM = Object.freeze({
  storeCount: 6,
  msgsPerSecPerStore: 20,
  rowsPerMsg: 64,
  gates: Object.freeze({ decodeP95Ms: 4, drops: 0, frameP95Ms: 16.7 }),
});
const MAGIC = 0x43564231;
const HEADER = 16;

/** @param {number} rows */
export function messageBytes(rows) {
  return HEADER + rows * (8 + 4 + 4 + 1);
}

/** Seeded message encoder (sender side). @returns {ArrayBuffer} */
export function encodeMessage(rng, storeId, seq, rows = STORM.rowsPerMsg) {
  const buf = new ArrayBuffer(messageBytes(rows));
  const dv = new DataView(buf);
  dv.setUint32(0, MAGIC, true);
  dv.setUint32(4, storeId, true);
  dv.setUint32(8, seq, true);
  dv.setUint32(12, rows, true);
  const time = new Float64Array(buf, HEADER, rows);
  const price = new Float32Array(buf, HEADER + rows * 8, rows);
  const qty = new Float32Array(buf, HEADER + rows * 12, rows);
  const side = new Uint8Array(buf, HEADER + rows * 16, rows);
  for (let i = 0; i < rows; i += 1) {
    time[i] = 1.7e12 + seq * 50 + i;
    price[i] = 60000 + rng() * 100;
    qty[i] = rng() * 5;
    side[i] = rng() < 0.5 ? 0 : 1;
  }
  return buf;
}

/** Receiver-side stores: per-store ring of the latest rows + ordering/drop accounting. */
export class StormStores {
  constructor(count = STORM.storeCount, capacity = 8192) {
    this.price = Array.from({ length: count }, () => new Float32Array(capacity));
    this.qty = Array.from({ length: count }, () => new Float32Array(capacity));
    this.head = new Int32Array(count);
    this.nextSeq = new Int32Array(count);
    this.applied = 0;
    this.gaps = 0; // a skipped sequence number == a dropped message
    this.duplicates = 0;
    this.capacity = capacity;
  }

  /** Decode + apply one message. Throws on a corrupt frame (a failure, not a drop). */
  decodeAndApply(buf) {
    const dv = new DataView(buf);
    if (dv.getUint32(0, true) !== MAGIC) throw new Error("B7: bad magic");
    const storeId = dv.getUint32(4, true);
    const seq = dv.getUint32(8, true);
    const rows = dv.getUint32(12, true);
    if (seq < this.nextSeq[storeId]) {
      this.duplicates += 1;
      return;
    }
    if (seq > this.nextSeq[storeId]) this.gaps += seq - this.nextSeq[storeId];
    this.nextSeq[storeId] = seq + 1;
    const price = new Float32Array(buf, HEADER + rows * 8, rows);
    const qty = new Float32Array(buf, HEADER + rows * 12, rows);
    const p = this.price[storeId];
    const q = this.qty[storeId];
    let h = this.head[storeId];
    for (let i = 0; i < rows; i += 1) {
      p[h] = price[i];
      q[h] = qty[i];
      h = (h + 1) % this.capacity;
    }
    this.head[storeId] = h;
    this.applied += 1;
  }
}

/**
 * Pure verdict used by the page, the worker and the unit tests.
 * @param {{ sent: number, applied: number, gaps: number, duplicates: number, decodeMs: number[] }} r
 */
export function evaluateStorm(r, percentile) {
  const decodeP95 = percentile(r.decodeMs, 95);
  const drops = Math.max(r.sent - r.applied, r.gaps);
  return {
    sent: r.sent,
    applied: r.applied,
    drops,
    duplicates: r.duplicates,
    decodeP95Ms: decodeP95,
    pass: decodeP95 <= STORM.gates.decodeP95Ms && drops === 0 && r.duplicates === 0,
  };
}

/**
 * Inline (main-thread) storm: real-time paced, no Worker. `now`/`sleep` are injected so
 * Node unit tests can run it on a fake clock. Returns raw measurements.
 * @param {{ durationMs: number, seed: number, now: () => number, sleep: (ms: number) => Promise<void> }} o
 */
export async function runStormInline(o) {
  const rng = mulberry32(o.seed ^ 0xb7);
  const stores = new StormStores();
  const decodeMs = [];
  const periodMs = 1000 / STORM.msgsPerSecPerStore;
  const total = Math.floor(o.durationMs / periodMs);
  const seqs = new Int32Array(STORM.storeCount);
  const t0 = o.now();
  let sent = 0;
  for (let tick = 0; tick < total; tick += 1) {
    const due = t0 + tick * periodMs;
    const wait = due - o.now();
    if (wait > 0) await o.sleep(wait);
    for (let s = 0; s < STORM.storeCount; s += 1) {
      const buf = encodeMessage(rng, s, seqs[s]++);
      sent += 1;
      const a = o.now();
      stores.decodeAndApply(buf);
      decodeMs.push(o.now() - a);
    }
  }
  return {
    sent,
    applied: stores.applied,
    gaps: stores.gaps,
    duplicates: stores.duplicates,
    decodeMs,
  };
}
