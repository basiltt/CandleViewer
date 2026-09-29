#!/usr/bin/env node
// E02-T10 "meta" test: assert the gate list in `scripts/run-verify-gate.mjs`
// (what `pnpm verify` composes) matches CONSTITUTION.md §9's 20-row required-
// check table one-for-one, in order (C-16.5 drift-protection pattern, same
// idea as scripts/check-agents-commands.mjs). This is the mechanical proof
// behind the ticket's acceptance scenario 1 ("verify executes exactly the
// same gate list as the PR required-checks table ... in order").
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");

const CHECK_ROW_RE = /^\|\s*(\d+)\s*\|\s*`([a-z0-9-]+)`\s*\|/;

/** @param {string} constitutionText */
export function parseConstitutionChecks(constitutionText) {
  const lines = constitutionText.split(/\r?\n/);
  const headerIdx = lines.findIndex((l) => l.trim().startsWith("| # | Check name"));
  if (headerIdx === -1) {
    throw new Error("CONSTITUTION.md has no '| # | Check name' §9 table header");
  }
  /** @type {{ n: number, name: string }[]} */
  const checks = [];
  for (let i = headerIdx + 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line.startsWith("|")) break;
    const match = CHECK_ROW_RE.exec(line);
    if (match) checks.push({ n: Number(match[1]), name: match[2] });
  }
  if (checks.length === 0) {
    throw new Error("no §9 check rows parsed — table format may have moved");
  }
  return checks;
}

/** @param {string} gateScriptText */
export function parseVerifyGateCalls(gateScriptText) {
  // Matches `gate(1, "lint", ...)` — ignores the non-numbered "guard" call,
  // which enforces C-9.4 and is intentionally extra (not one of the 20).
  const re = /gate\(\s*(\d+)\s*,\s*"([a-z0-9-]+)"/g;
  /** @type {{ n: number, name: string }[]} */
  const calls = [];
  let m;
  while ((m = re.exec(gateScriptText)) !== null) {
    calls.push({ n: Number(m[1]), name: m[2] });
  }
  return calls;
}

/**
 * @param {{ n: number, name: string }[]} expected
 * @param {{ n: number, name: string }[]} actual
 */
export function diffGateLists(expected, actual) {
  const missing = [];
  const mismatched = [];
  const byN = new Map(actual.map((c) => [c.n, c.name]));
  for (const e of expected) {
    const gotName = byN.get(e.n);
    if (gotName === undefined) {
      missing.push(`#${e.n} ${e.name}`);
    } else if (gotName !== e.name) {
      mismatched.push(`#${e.n}: expected "${e.name}", got "${gotName}"`);
    }
  }
  return { missing, mismatched };
}

/* c8 ignore start -- CLI entrypoint, exercised via unit tests on the pure functions above */
function main() {
  const constitutionText = readFileSync(path.join(REPO_ROOT, "CONSTITUTION.md"), "utf8");
  const gateScriptText = readFileSync(
    path.join(REPO_ROOT, "scripts", "run-verify-gate.mjs"),
    "utf8",
  );
  const expected = parseConstitutionChecks(constitutionText);
  const actual = parseVerifyGateCalls(gateScriptText);
  const { missing, mismatched } = diffGateLists(expected, actual);

  if (missing.length > 0 || mismatched.length > 0) {
    if (missing.length > 0) {
      console.error(
        `check-verify-gate-list: scripts/run-verify-gate.mjs is missing gate(s) from CONSTITUTION.md §9: ${missing.join(", ")}`,
      );
    }
    if (mismatched.length > 0) {
      console.error(
        `check-verify-gate-list: gate number/name mismatch vs CONSTITUTION.md §9: ${mismatched.join("; ")}`,
      );
    }
    process.exit(1);
  }
  console.log(
    `check-verify-gate-list: scripts/run-verify-gate.mjs matches all ${expected.length} of CONSTITUTION.md §9's required checks.`,
  );
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}
