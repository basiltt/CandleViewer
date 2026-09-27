#!/usr/bin/env node
// Generates TS types from docs/plan/22-api-openapi.yaml via openapi-typescript,
// then prepends the repo's standard generated-file header (openapi-typescript's
// own banner is suppressed with --banner false equivalent — the CLI doesn't
// support that, so we strip its header and add ours for consistency with the
// WS-generated output and the header-guard lint).
import { writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import openapiTS, { astToString } from "openapi-typescript";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(__dirname, "..", "..", "..");
const specPath = join(repoRoot, "docs", "plan", "22-api-openapi.yaml");
const outDir = join(__dirname, "..", "src", "generated", "rest");
const outPath = join(outDir, "index.ts");

const HEADER = `// ==========================================================================
// GENERATED FILE — DO NOT EDIT BY HAND.
// Regenerate with \`pnpm --filter @candleviewer/protocol generate\`.
// Source: docs/plan/22-api-openapi.yaml, via openapi-typescript. Hand edits
// are rejected by the header-guard lint
// (packages/protocol/scripts/check-generated-guard.mjs) and by
// \`linguist-generated\` in .gitattributes.
// ==========================================================================
/* eslint-disable */

`;

async function main() {
  mkdirSync(outDir, { recursive: true });

  const ast = await openapiTS(new URL(`file://${specPath.replace(/\\/g, "/")}`), {
    alphabetize: true,
  });
  const body = astToString(ast);

  writeFileSync(outPath, HEADER + body, "utf8");
  console.log(`[generate-rest-types] wrote ${outPath}.`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
