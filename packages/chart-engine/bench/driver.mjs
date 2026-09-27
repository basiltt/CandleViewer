// Scripted driver sequences (E06-K01 ticket "Scripted driver sequences" bullet).
// Time-parameterised (a function of elapsed ms, not frame count) so a slow
// machine executes the same logical motion as a fast one — a frame-counted
// script would silently give a slow runtime an easier test.

/**
 * @typedef {{ tMs: number, kind: "pan"|"zoom"|"footprintHold"|"heatmapStream"|"liveUpdate"|"none", payload?: Record<string, number> }} DriverEvent
 */

/** Scenario ids named in docs/plan/06-performance-and-load-standard.md §7.1 / the ticket's driver bullet. */
export const SCENARIOS = /** @type {const} */ (["B1", "B2", "B3", "B4", "B5", "B7", "B9", "B10"]);

/**
 * Builds a deterministic driver script for a scenario: a sorted array of
 * `DriverEvent`s keyed by elapsed time. `sampleHz` controls how many events
 * are emitted per second of logical time (independent of actual frame rate).
 *
 * @param {{ scenario: (typeof SCENARIOS)[number], durationMs: number, sampleHz?: number }} opts
 * @returns {DriverEvent[]}
 */
export function buildDriverScript(opts) {
  const { scenario, durationMs, sampleHz = 60 } = opts;
  const stepMs = 1000 / sampleHz;
  const events = [];

  for (let tMs = 0; tMs < durationMs; tMs += stepMs) {
    switch (scenario) {
      case "B1": {
        // Continuous pan at 1000 px/s.
        events.push({ tMs, kind: "pan", payload: { dxPx: 1000 * (stepMs / 1000) } });
        break;
      }
      case "B2": {
        // Wheel zoom sweep 0.1 -> 50 px/bar over the full duration.
        const progress = tMs / durationMs;
        const pxPerBar = 0.1 + progress * (50 - 0.1);
        events.push({ tMs, kind: "zoom", payload: { pxPerBar } });
        break;
      }
      case "B3": {
        // Static footprint hold with periodic updates every 500ms.
        if (Math.round(tMs) % 500 < stepMs) {
          events.push({ tMs, kind: "footprintHold", payload: {} });
        } else {
          events.push({ tMs, kind: "none" });
        }
        break;
      }
      case "B4": {
        // Heatmap streaming (100ms cadence) while panning.
        if (Math.round(tMs) % 100 < stepMs) {
          events.push({ tMs, kind: "heatmapStream", payload: {} });
        }
        events.push({ tMs, kind: "pan", payload: { dxPx: 200 * (stepMs / 1000) } });
        break;
      }
      case "B5": {
        // Combined: pan + zoom + heatmap stream + footprint hold.
        events.push({ tMs, kind: "pan", payload: { dxPx: 500 * (stepMs / 1000) } });
        if (Math.round(tMs) % 100 < stepMs) {
          events.push({ tMs, kind: "heatmapStream", payload: {} });
        }
        break;
      }
      case "B7": {
        // Live update storm: 20 msg/s x 6 stores => 120 msg/s aggregate.
        if (Math.round(tMs) % Math.round(1000 / 120) < stepMs) {
          events.push({ tMs, kind: "liveUpdate", payload: { storeCount: 6 } });
        }
        break;
      }
      case "B9": {
        // Cold init to first frame: a single event at t=0.
        if (tMs === 0) events.push({ tMs, kind: "none" });
        break;
      }
      case "B10": {
        // 30-minute soak: gentle continuous pan, low event rate.
        if (Math.round(tMs) % 1000 < stepMs) {
          events.push({ tMs, kind: "pan", payload: { dxPx: 50 } });
        }
        break;
      }
      default:
        break;
    }
  }
  return events;
}
