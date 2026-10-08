// Pure helpers shared by the page, the runner and unit tests (no DOM, no Node APIs).
import { percentile } from "../stats.mjs";

/** @param {number[]} frameMs */
export function summariseFrames(frameMs) {
  return {
    p50: percentile(frameMs, 50),
    p95: percentile(frameMs, 95),
    p99: percentile(frameMs, 99),
    outliers33: frameMs.filter((v) => v > 33).length,
    maxMs: frameMs.reduce((a, b) => (b > a ? b : a), 0),
  };
}

/**
 * Per-bucket soak series (ADR-0011 criteria 2 and 3): outlier count and median
 * texSubImage2D time per `bucketMs` of logical time, so progressive degradation
 * is visible as a trend rather than hidden in one pooled percentile.
 * @param {number[]} frameAt
 * @param {number[]} frameMs
 * @param {number[]} upAt
 * @param {number[]} upMs
 * @param {number} bucketMs
 */
export function soakBuckets(frameAt, frameMs, upAt, upMs, bucketMs) {
  const last = frameAt.reduce((a, b) => (b > a ? b : a), 0);
  const n = Math.max(1, Math.ceil((last + 1) / bucketMs));
  const out = [];
  for (let b = 0; b < n; b += 1) {
    const lo = b * bucketMs;
    const hi = lo + bucketMs;
    const f = frameMs.filter((_, i) => frameAt[i] >= lo && frameAt[i] < hi);
    const u = upMs.filter((_, i) => upAt[i] >= lo && upAt[i] < hi);
    if (f.length === 0 && u.length === 0) continue;
    out.push({
      bucket: b,
      frames: f.length,
      p95: percentile(f, 95),
      outliers33: f.filter((v) => v > 33).length,
      texUploadMedianMs: u.length ? percentile(u, 50) : null,
    });
  }
  return out;
}
