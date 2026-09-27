#!/usr/bin/env node
// E03-T02 CI-JS-001: assert the Node version pinned in `.nvmrc` satisfies the
// root `package.json#engines.node` range. A mismatch fails fast, before any
// install/lint/test step runs, rather than surfacing as a confusing
// downstream failure in a random package.
//
// Usage: node tools/ci/check-node-version.mjs

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repoRoot = path.resolve(fileURLToPath(import.meta.url), "..", "..", "..");

function readNvmrc(root) {
  return readFileSync(path.join(root, ".nvmrc"), "utf8").trim();
}

function readEnginesRange(root) {
  const pkg = JSON.parse(readFileSync(path.join(root, "package.json"), "utf8"));
  const range = pkg.engines && pkg.engines.node;
  if (!range) {
    throw new Error("root package.json is missing engines.node");
  }
  return range;
}

// Minimal semver range check for the ">=X.Y.Z <A" shape used in this repo's
// package.json#engines — no external dependency needed for one comparison.
export function nvmrcSatisfiesEngines(nvmrc, enginesRange) {
  const version = nvmrc.replace(/^v/, "").trim();
  const parts = version.split(".").map(Number);
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) {
    return false;
  }
  const [major, minor, patch] = parts;
  const value = major * 1_000_000 + minor * 1_000 + patch;

  const clauses = enginesRange.trim().split(/\s+/);
  return clauses.every((clause) => {
    const match = clause.match(/^(>=|<=|>|<|=)(\d+)(?:\.(\d+))?(?:\.(\d+))?$/);
    if (!match) {
      throw new Error(`unsupported engines.node clause: "${clause}"`);
    }
    const [, op, ma, mi = "0", pa = "0"] = match;
    const bound = Number(ma) * 1_000_000 + Number(mi) * 1_000 + Number(pa);
    switch (op) {
      case ">=":
        return value >= bound;
      case "<=":
        return value <= bound;
      case ">":
        return value > bound;
      case "<":
        return value < bound;
      case "=":
        return value === bound;
      default:
        return false;
    }
  });
}

function main() {
  const nvmrc = readNvmrc(repoRoot);
  const enginesRange = readEnginesRange(repoRoot);

  if (!nvmrcSatisfiesEngines(nvmrc, enginesRange)) {
    process.stderr.write(
      [
        `CI-JS-001: .nvmrc ("${nvmrc}") does not satisfy package.json#engines.node ("${enginesRange}").`,
        "Update .nvmrc or package.json#engines so they agree, then re-run.",
        "",
      ].join("\n"),
    );
    process.exit(1);
  }

  process.stdout.write(`.nvmrc (${nvmrc}) satisfies engines.node (${enginesRange})\n`);
}

const isMain = process.argv[1] && process.argv[1].endsWith("check-node-version.mjs");
if (isMain) {
  main();
}
