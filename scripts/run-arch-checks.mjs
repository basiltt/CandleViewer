#!/usr/bin/env node
// E02-T06: `pnpm arch` / `make arch` — runs every architecture-boundary gate
// in one command (CONSTITUTION.md §3, C-3.1..C-3.5, §9 #18):
//   1. drift check: docs/plan/module-contracts.toml -> services/api/.importlinter
//      (fails if the committed file is stale vs the manifest)
//   2. dependency-cruiser (frontend module boundaries, .dependency-cruiser.js)
//   3. import-linter (backend module boundaries, services/api/.importlinter)
//
// Each step's name and rule ids are echoed so a CI failure is self-explanatory
// (Constitution preamble: "reviewers cite rule ids in PRs"). Non-zero exit on
// the first failing step, after finishing all steps run so far (fail-fast).

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");

/**
 * @param {string} label
 * @param {string} command
 * @param {string[]} args
 * @param {import("node:child_process").SpawnSyncOptions} [opts]
 */
function step(label, command, args, opts = {}) {
  console.log(`\n> arch: ${label}`);
  const result = spawnSync(command, args, {
    cwd: REPO_ROOT,
    stdio: "inherit",
    shell: process.platform === "win32",
    ...opts,
  });
  if (result.status !== 0) {
    console.error(`\narch: FAILED at step "${label}" (exit ${result.status})`);
    process.exit(result.status ?? 1);
  }
}

step("module-contracts.toml -> services/api/.importlinter drift check", "python", [
  "scripts/gen_importlinter_contracts.py",
  "--check",
]);

const frontendTargets = ["packages"];
if (existsSync(path.join(REPO_ROOT, "apps"))) frontendTargets.push("apps");
step("dependency-cruiser (frontend module boundaries, C-2.16 / C-3.5 / §9 #18)", "npx", [
  "--no-install",
  "depcruise",
  "--config",
  ".dependency-cruiser.js",
  "--output-type",
  "err-long",
  ...frontendTargets,
]);

step(
  "import-linter (backend module boundaries, CONSTITUTION.md §3, C-3.1..C-3.5)",
  "uv",
  ["run", "lint-imports"],
  { cwd: path.join(REPO_ROOT, "services", "api") },
);

console.log("\narch: all checks passed.");
