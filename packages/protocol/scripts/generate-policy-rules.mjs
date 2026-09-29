#!/usr/bin/env node
// Generates the TS `InstrumentPolicy` port and its rule-table type
// (ticket `E08-S02`, "Client and server never disagree" scenario).
//
// Two Python scripts under tools/gen/ are the actual sources of truth this
// step consumes (both stdlib-only, run without a `uv sync` — see their own
// docstrings for why the freshness gate demands that):
//   - export_instrument_policy_rules.py -> packages/fixtures/golden/policy/rules.json
//     (the stable enum-value tables: violation codes, round modes)
//   - export_instrument_policy_corpus.py -> packages/fixtures/golden/policy/corpus.json
//     (the cross-language equivalence fixture consumed by
//     test/policy-equivalence.test.ts and
//     services/api/tests/unit/exchange/test_policy_corpus_equivalence.py)
//
// This script only re-renders rules.json into a generated TS literal-union
// module; it does not invent any new data. The rounding/validation
// *algorithm* itself lives, hand-ported once, in src/rules/policy.ts (NOT
// generated — same convention as src/runtime/index.ts's hand-written binary
// decoder) and is proven identical to the Python original by the shared
// corpus, not by this generator.
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import prettier from "prettier";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(__dirname, "..", "..", "..");
const rulesJsonPath = join(repoRoot, "packages", "fixtures", "golden", "policy", "rules.json");
const outDir = join(__dirname, "..", "src", "generated", "policy");
const outPath = join(outDir, "index.ts");

const HEADER = `// ==========================================================================
// GENERATED FILE — DO NOT EDIT BY HAND.
// Regenerate with \`pnpm --filter @candleviewer/protocol generate\`.
// Source: tools/gen/export_instrument_policy_rules.py, itself mirroring
// services/api/candleviewer/exchange/policy.py verbatim. Hand edits are
// rejected by the header-guard lint
// (packages/protocol/scripts/check-generated-guard.mjs) and by
// \`linguist-generated\` in .gitattributes.
// ==========================================================================
/* eslint-disable */

`;

function runPythonGenerator(scriptRelPath) {
  // Prefer python3, fall back to python (Windows dev boxes commonly only
  // have the latter on PATH); the CI runner (actions/setup-python) always
  // provides "python".
  const candidates = ["python3", "python"];
  let lastErr;
  for (const bin of candidates) {
    try {
      execFileSync(bin, [join(repoRoot, ...scriptRelPath)], { cwd: repoRoot, stdio: "pipe" });
      return;
    } catch (err) {
      lastErr = err;
    }
  }
  throw new Error(
    `[generate-policy-rules] could not run ${scriptRelPath.join("/")} with ` +
      `python3 or python: ${lastErr?.message ?? "unknown error"}`,
  );
}

function tsUnion(values) {
  return values.map((v) => JSON.stringify(v)).join(" | ");
}

async function main() {
  runPythonGenerator(["tools", "gen", "export_instrument_policy_rules.py"]);
  runPythonGenerator(["tools", "gen", "export_instrument_policy_corpus.py"]);
  const rules = JSON.parse(readFileSync(rulesJsonPath, "utf8"));

  mkdirSync(outDir, { recursive: true });

  const body = `
/** Mirrors \`FilterViolationCode\` in services/api/candleviewer/exchange/policy.py. */
export type FilterViolationCode = ${tsUnion(rules.violation_codes)};

export const FILTER_VIOLATION_CODES: readonly FilterViolationCode[] = ${JSON.stringify(
    rules.violation_codes,
  )};

/** Mirrors \`PriceRoundMode\`. Ticket scope: only "nearest" is implemented. */
export type PriceRoundMode = ${tsUnion(rules.price_round_modes)};

/** Mirrors \`QtyRoundMode\`. Ticket scope: only "down" (floor) is implemented. */
export type QtyRoundMode = ${tsUnion(rules.qty_round_modes)};
`;

  const config = (await prettier.resolveConfig(outPath)) ?? {};
  const formatted = await prettier.format(HEADER + body, { ...config, filepath: outPath });
  writeFileSync(outPath, formatted, "utf8");
  console.log(`[generate-policy-rules] wrote ${outPath}.`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
