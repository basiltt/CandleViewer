#!/usr/bin/env node
// E03-T02: `pnpm audit --audit-level=high` hand-off marker for E03-T07 (the
// npm-audit / licence-scanning security lane owns *failing* the build on
// findings; this lane only produces the artifact so that lane can consume
// it without re-running the audit). `pnpm audit` exits non-zero when it
// finds anything at/above the given level, so this script's job is just to
// make sure a JSON report file always exists (even an empty/error one) for
// the upload-artifact step, and to never itself fail the js lane.
//
// Usage: node tools/ci/mark-audit-handoff.mjs <path-to-audit-json>

import { existsSync, writeFileSync } from "node:fs";

function main() {
  const outPath = process.argv[2];
  if (!outPath) {
    process.stderr.write("usage: mark-audit-handoff.mjs <path-to-audit-json>\n");
    process.exit(1);
  }

  if (existsSync(outPath)) {
    // `pnpm audit --json` already wrote a report (it exits non-zero on
    // findings but still emits JSON); nothing to do.
    process.stdout.write(
      `pnpm audit report present at ${outPath}; hand-off marker deferred to E03-T07\n`,
    );
    return;
  }

  // `pnpm audit` failed before producing JSON (e.g. registry unreachable in
  // an offline dev sandbox) — write a placeholder so the artifact upload
  // step has something to pick up, clearly marked as not a real result.
  writeFileSync(
    outPath,
    JSON.stringify(
      {
        marker: "pnpm-audit-handoff",
        status: "not-run",
        reason: "pnpm audit did not produce a report; see E03-T07 for the enforced audit gate",
      },
      null,
      2,
    ),
  );
  process.stdout.write(`wrote placeholder audit hand-off marker to ${outPath}\n`);
}

main();
