// Statistical rules (E06-K01 ticket "Statistical rules are enforced by the
// tool" AC): p50/p95/p99, >=3-repetition admissibility gate, median-of-p95
// comparison across repeated runs (§7.4).

/**
 * Computes the p-th percentile (nearest-rank) of a numeric array. Does not
 * mutate the input.
 * @param {number[]} values
 * @param {number} p in [0, 100]
 */
export function percentile(values, p) {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const rank = Math.ceil((p / 100) * sorted.length) - 1;
  const idx = Math.min(sorted.length - 1, Math.max(0, rank));
  return sorted[idx];
}

/**
 * @param {number[]} frameTimesMs
 * @returns {{ p50: number, p95: number, p99: number }}
 */
export function summarizePercentiles(frameTimesMs) {
  return {
    p50: percentile(frameTimesMs, 50),
    p95: percentile(frameTimesMs, 95),
    p99: percentile(frameTimesMs, 99),
  };
}

/** Default repetition count (ticket AC: "the default repetition count is 3"). */
export const DEFAULT_REPETITIONS = 3;
/** Minimum repetitions for a run's numbers to count as ADR evidence (§7.4). */
export const MIN_ADMISSIBLE_REPETITIONS = 3;

/**
 * Applies the ticket's admissibility rule: fewer than 3 repetitions is
 * marked "not admissible for ADR evidence" rather than silently accepted.
 * @param {number} repetitions
 */
export function isAdmissible(repetitions) {
  return repetitions >= MIN_ADMISSIBLE_REPETITIONS;
}

/**
 * Given per-repetition p95 values, returns the median — the figure the CI
 * regression gate compares against baseline (§7.4: "compares the median of
 * those repeated p95s, not a single noisy sample").
 * @param {number[]} p95PerRep
 */
export function medianOfP95(p95PerRep) {
  if (p95PerRep.length === 0) return 0;
  const sorted = [...p95PerRep].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 0) {
    return (sorted[mid - 1] + sorted[mid]) / 2;
  }
  return sorted[mid];
}
