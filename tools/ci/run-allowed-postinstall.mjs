#!/usr/bin/env node
// E03-T02 SR-138: after `pnpm install --frozen-lockfile --ignore-scripts`,
// explicitly (re)run the lifecycle scripts for the small, reviewed allowlist
// in tools/ci/allowed-postinstall.json — instead of flipping
// `ignore-scripts` off repo-wide. Mirrors the exception already documented
// in `pnpm-workspace.yaml`'s `allowBuilds` block.
//
// Usage: node tools/ci/run-allowed-postinstall.mjs

import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repoRoot = path.resolve(fileURLToPath(import.meta.url), "..", "..", "..");

export function loadAllowlist(root) {
  const raw = readFileSync(path.join(root, "tools", "ci", "allowed-postinstall.json"), "utf8");
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed.packages)) {
    throw new Error("tools/ci/allowed-postinstall.json is missing a packages[] array");
  }
  return parsed.packages.map((entry) => entry.name);
}

function main() {
  const names = loadAllowlist(repoRoot);
  if (names.length === 0) {
    process.stdout.write("no allowlisted postinstall packages configured\n");
    return;
  }

  process.stdout.write(`running pnpm rebuild for allowlisted packages: ${names.join(", ")}\n`);
  execFileSync("pnpm", ["rebuild", ...names], {
    cwd: repoRoot,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
}

const isMain = process.argv[1] && process.argv[1].endsWith("run-allowed-postinstall.mjs");
if (isMain) {
  main();
}
