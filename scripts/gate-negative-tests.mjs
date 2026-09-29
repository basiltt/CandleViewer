#!/usr/bin/env node
// E02-T10: negative-test harness (ticket "Negative-test harness" deliverable).
// For each gate this ticket implements or wires locally, applies a temporary
// breaking change, asserts the gate fails with the expected signal, then
// reverts the change -- proving the gate is real rather than a decorative
// no-op. Scoped to gates whose failure mode is safe and fast to simulate on
// a workstation (no docker/CodeQL/Trivy scenarios here; those gates are
// themselves `ciOnly()` placeholders in scripts/run-verify-gate.mjs and are
// out of scope per the ticket body).
//
// Usage: node scripts/gate-negative-tests.mjs
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");

let failures = 0;

/**
 * @param {string} name
 * @param {() => void | Promise<void>} fn
 */
async function scenario(name, fn) {
  console.log(`\n> gate-negative-test: ${name}`);
  try {
    await fn();
    console.log(`  PASS: ${name}`);
  } catch (err) {
    failures += 1;
    console.error(`  FAIL: ${name}\n  ${err.message}`);
  }
}

function run(command, args, opts = {}) {
  return spawnSync(command, args, {
    cwd: REPO_ROOT,
    encoding: "utf8",
    shell: process.platform === "win32",
    ...opts,
  });
}

function assertFails(result, label) {
  if (result.status === 0) {
    throw new Error(`expected "${label}" to fail (non-zero exit) but it exited 0`);
  }
}

async function main() {
  // --- Scenario 1: threshold-guard catches a coverage-floor decrease (C-9.4) ---
  await scenario("threshold-guard fails on an un-amended coverage decrease", () => {
    const qgPath = path.join(REPO_ROOT, "quality-gates.json");
    const original = readFileSync(qgPath, "utf8");
    const parsed = JSON.parse(original);
    parsed.coverage["services/api"].lines -= 10;
    writeFileSync(qgPath, JSON.stringify(parsed, null, 2) + "\n", "utf8");
    // Snapshot the pre-mutation file to disk so the guard has a known "old"
    // baseline to diff against, independent of whether `quality-gates.json`
    // itself already exists on `origin/main` (it may not, on the PR that
    // first introduces it).
    const oldSnapshotPath = path.join(REPO_ROOT, "quality-gates.old.negtest.json");
    writeFileSync(oldSnapshotPath, original, "utf8");
    try {
      const result = run("python", [
        "tools/ci/quality_gates.py",
        "--old-path",
        "quality-gates.old.negtest.json",
      ]);
      assertFails(result, "threshold-guard");
      if (!/C-9\.4/.test(result.stdout + result.stderr)) {
        throw new Error("expected the failure message to cite C-9.4");
      }
    } finally {
      writeFileSync(qgPath, original, "utf8");
      rmSync(oldSnapshotPath, { force: true });
    }
  });

  // --- Scenario 2: flaky-quarantine report fails on an unreferenced @flaky marker ---
  await scenario("flaky-quarantine report fails on an unreferenced @flaky marker", () => {
    const tmpDir = mkdtempSync(path.join(tmpdir(), "cv-flaky-neg-"));
    try {
      writeFileSync(
        path.join(tmpDir, "test_unreferenced.py"),
        "@pytest.mark.flaky\ndef test_x(): pass\n",
        "utf8",
      );
      const result = run("python", [
        path.join(REPO_ROOT, "tools", "ci", "flaky_quarantine_report.py"),
        "--repo-root",
        tmpDir,
        "--out",
        "reports/flaky-quarantine.json",
      ]);
      assertFails(result, "flaky-quarantine report");
    } finally {
      rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  // --- Scenario 3: bundle-size regression check fails on a >5% growth ---
  await scenario("bundle-size regression check fails on >5% growth vs baseline", async () => {
    const mod = new URL("./check-bundle-size-regression.mjs", import.meta.url).href;
    const { checkRegressions } = await import(mod);
    const violations = checkRegressions({ "dist/assets/*.js": 1_000_000 }, [
      { name: "dist/assets/*.js", size: 1_100_000 },
    ]);
    if (violations.length === 0) {
      throw new Error("expected a violation for +10% growth but got none");
    }
  });

  // --- Scenario 4: check-verify-gate-list fails when a §9 check is missing ---
  await scenario("check-verify-gate-list fails when the gate script is missing a §9 check", () => {
    const gateScriptPath = path.join(REPO_ROOT, "scripts", "run-verify-gate.mjs");
    const original = readFileSync(gateScriptPath, "utf8");
    const mutated = original.replace(/gate\(20, "pr-metadata".*\n/, "");
    if (mutated === original) {
      throw new Error("fixture did not match — run-verify-gate.mjs's source moved");
    }
    writeFileSync(gateScriptPath, mutated, "utf8");
    try {
      const result = run("node", ["scripts/check-verify-gate-list.mjs"]);
      assertFails(result, "check-verify-gate-list");
    } finally {
      writeFileSync(gateScriptPath, original, "utf8");
    }
  });

  if (failures > 0) {
    console.error(`\ngate-negative-tests: ${failures} scenario(s) FAILED (a gate is not real).`);
    process.exitCode = 1;
  } else {
    console.log("\ngate-negative-tests: all scenarios proved their gate fails as expected.");
  }
}

await main();
