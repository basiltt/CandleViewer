/**
 * Data contract for the compact latency indicator (E04-T06) consumed by
 * CMP-208 StatusBar (`latencyMs`) and CMP-210 HealthChips. The widgets are
 * E10's; this module only fixes the shape: numeric value + explicit unit +
 * a state word (never colour alone, 05-accessibility-standard.md), with
 * updates throttled to ≤1 Hz so a `role="status"` region never spams.
 */

export type LatencyState = "ok" | "degraded" | "breach" | "unavailable";

export interface LatencyIndicator {
  /** Rounded milliseconds, or `null` when unavailable. */
  readonly valueMs: number | null;
  readonly unit: "ms";
  readonly state: LatencyState;
  /** Accessible name, e.g. "WS latency: ok, 38 ms". */
  readonly label: string;
}

/** Budget #3 (06-performance §2): p95 < 100 ms, p99 < 250 ms. */
export const LATENCY_OK_MS = 100;
export const LATENCY_BREACH_MS = 250;
export const INDICATOR_MIN_INTERVAL_MS = 1_000;

export function toLatencyIndicator(ms: number | null): LatencyIndicator {
  if (ms === null || !Number.isFinite(ms) || ms < 0) {
    return { valueMs: null, unit: "ms", state: "unavailable", label: "WS latency: unavailable" };
  }
  const valueMs = Math.round(ms);
  const state: LatencyState =
    valueMs < LATENCY_OK_MS ? "ok" : valueMs < LATENCY_BREACH_MS ? "degraded" : "breach";
  return { valueMs, unit: "ms", state, label: `WS latency: ${state}, ${valueMs} ms` };
}

/** Emits at most once per `INDICATOR_MIN_INTERVAL_MS` (leading edge). */
export function throttleIndicator(
  emit: (v: LatencyIndicator) => void,
  now: () => number = () => Date.now(),
): (ms: number | null) => void {
  let last = -Infinity;
  return (ms) => {
    const t = now();
    if (t - last < INDICATOR_MIN_INTERVAL_MS) return;
    last = t;
    emit(toLatencyIndicator(ms));
  };
}
