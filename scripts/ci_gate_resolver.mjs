#!/usr/bin/env node
// ci-required resolver (ADR-0013-ci-pipeline.md binding rule 2, E03-T01).
//
// Computes the final conclusion for the `ci-required` gate job from the
// `changed-paths` filter outputs and each lane's `needs.<lane>.result`.
// Exported as a pure function so it can be unit-tested without GitHub
// Actions context; the CLI entry point below is what `actions/github-script`
// invokes from `.github/workflows/pr.yml`.
//
// Rules:
//   - applicable (filter true) and result != 'success' -> fail (CI-GATE-001)
//   - not applicable (filter false) and result == 'skipped' -> ok
//   - applicable (filter true) and result == 'skipped' -> fail (CI-GATE-002),
//     "gate misconfiguration: <lane> applicable but skipped"
//   - not applicable and result != 'skipped' (e.g. it ran anyway) -> ok,
//     a lane running unnecessarily is not a gate failure.

/**
 * @typedef {"success"|"failure"|"cancelled"|"skipped"} LaneResult
 * @typedef {{ applicable: boolean, result: LaneResult }} LaneInput
 * @typedef {{ ok: boolean, code: string | null, reason: string | null }} LaneOutcome
 */

/** @param {string} name @param {LaneInput} input @returns {LaneOutcome} */
function evaluateLane(name, { applicable, result }) {
  if (applicable && result === "skipped") {
    return {
      ok: false,
      code: "CI-GATE-002",
      reason: `gate misconfiguration: ${name} applicable but skipped`,
    };
  }
  if (applicable && result !== "success") {
    return {
      ok: false,
      code: "CI-GATE-001",
      reason: `${name} required and not successful (result: ${result})`,
    };
  }
  return { ok: true, code: null, reason: null };
}

/**
 * @param {Record<string, LaneInput>} lanes
 * @returns {{ conclusion: "success" | "failure", failures: LaneOutcome[] }}
 */
export function resolveGate(lanes) {
  const failures = [];
  for (const [name, input] of Object.entries(lanes)) {
    const outcome = evaluateLane(name, input);
    if (!outcome.ok) failures.push(outcome);
  }
  return {
    conclusion: failures.length === 0 ? "success" : "failure",
    failures,
  };
}

export { evaluateLane };

// --- CLI entry point (used by actions/github-script step) -----------------
// Reads lane definitions from argv[2] as a JSON string:
//   { "js": {"applicable": true, "result": "success"}, ... }
// Exits 0 on success, 1 on failure, printing each failure reason to stderr.
async function main() {
  const raw = process.argv[2];
  if (!raw) {
    console.error("usage: node ci_gate_resolver.mjs '<lanes-json>'");
    process.exit(2);
  }
  /** @type {Record<string, LaneInput>} */
  const lanes = JSON.parse(raw);
  const { conclusion, failures } = resolveGate(lanes);
  for (const f of failures) {
    console.error(`${f.code}: ${f.reason}`);
  }
  console.log(`ci-required conclusion: ${conclusion}`);
  process.exit(conclusion === "success" ? 0 : 1);
}

// Only run the CLI when this file is the process entry point (not when
// imported by the vitest suite).
if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
