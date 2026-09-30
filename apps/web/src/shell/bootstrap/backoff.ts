/**
 * WS reconnect backoff sequence (`docs/plan/23-ws-protocol.md` §9.2).
 * The delay/jitter table is a contract-test assertion, not a suggestion —
 * do not "simplify" it into a formula that drifts from the table.
 */

export interface BackoffStep {
  readonly delayMs: number;
  readonly jitterMs: number;
}

/** §9.2 table, 1-indexed by attempt; attempt 6+ repeats the last row. */
const BACKOFF_TABLE: readonly BackoffStep[] = [
  { delayMs: 500, jitterMs: 250 },
  { delayMs: 1_000, jitterMs: 500 },
  { delayMs: 2_000, jitterMs: 1_000 },
  { delayMs: 5_000, jitterMs: 2_000 },
  { delayMs: 10_000, jitterMs: 5_000 },
  { delayMs: 30_000, jitterMs: 10_000 },
];

/** Returns the nominal `{delayMs, jitterMs}` pair for a 1-indexed attempt number. */
export function backoffStepFor(attempt: number): BackoffStep {
  const index = Math.min(Math.max(attempt, 1), BACKOFF_TABLE.length) - 1;
  return BACKOFF_TABLE.at(index) as BackoffStep;
}

/**
 * Full-jitter delay for a given attempt: `delayMs +/- jitterMs`, clamped to
 * a non-negative value. `random` is injectable for deterministic tests.
 */
export function backoffDelayWithJitter(
  attempt: number,
  random: () => number = Math.random,
): number {
  const { delayMs, jitterMs } = backoffStepFor(attempt);
  const offset = (random() * 2 - 1) * jitterMs;
  return Math.max(0, Math.round(delayMs + offset));
}
