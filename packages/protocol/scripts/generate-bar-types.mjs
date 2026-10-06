#!/usr/bin/env node
// Generates the TS mirror of the bar domain model (ticket E12-T01,
// docs/plan/24-internal-schemas.md §3.1-§3.2) so the client cannot drift
// from the server model.
//
// Source of truth: services/api/candleviewer/bars/models.py. Pydantic renders
// it (serialization mode: Decimals as strings) to the committed JSON Schema
// packages/fixtures/golden/bars/bar-model.schema.json via
// services/api/scripts/generate_bar_artifacts.py — that step needs pydantic
// and is drift-checked on the Python side (tests/unit/bars). This script only
// compiles that committed schema to TypeScript, so it runs without a Python
// environment (same split as generate-policy-rules.mjs).
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { compile } from "json-schema-to-typescript";
import prettier from "prettier";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(__dirname, "..", "..", "..");
const schemaPath = join(
  repoRoot,
  "packages",
  "fixtures",
  "golden",
  "bars",
  "bar-model.schema.json",
);
const outDir = join(__dirname, "..", "src", "generated", "bars");
const outPath = join(outDir, "index.ts");

const HEADER = `// ==========================================================================
// GENERATED FILE — DO NOT EDIT BY HAND.
// Regenerate with \`pnpm --filter @candleviewer/protocol generate\`.
// Source: packages/fixtures/golden/bars/bar-model.schema.json, rendered from
// services/api/candleviewer/bars/models.py by
// services/api/scripts/generate_bar_artifacts.py. Hand edits are rejected by
// the header-guard lint (packages/protocol/scripts/check-generated-guard.mjs).
// ==========================================================================
/* eslint-disable */

`;

async function main() {
  const doc = JSON.parse(readFileSync(schemaPath, "utf8"));
  // Strip per-property titles so scalar fields inline (no `Kind`/`Index` alias clutter or
  // name collisions between BarSpec.kind and BarUpdate.kind); keep $defs titles.
  const defs = JSON.parse(JSON.stringify(doc.$defs));
  for (const def of Object.values(defs)) {
    for (const prop of Object.values(def.properties ?? {})) delete prop.title;
  }
  const root = {
    title: "BarModel",
    type: "object",
    additionalProperties: false,
    properties: {
      spec: { $ref: "#/$defs/BarSpec" },
      bar: { $ref: "#/$defs/Bar" },
      update: { $ref: "#/$defs/BarUpdate" },
    },
    $defs: defs,
  };
  const ts = await compile(root, "BarModel", {
    bannerComment: "",
    style: { semi: true, singleQuote: false },
    additionalProperties: false,
    unreachableDefinitions: false,
  });
  // The synthetic root only anchors the three models; it is not part of the domain.
  const body = ts.replace(/export interface BarModel \{[^}]*\}\n*/, "");
  const chunks = [HEADER, body];
  mkdirSync(outDir, { recursive: true });
  const config = (await prettier.resolveConfig(outPath)) ?? {};
  writeFileSync(
    outPath,
    await prettier.format(chunks.join("\n"), { ...config, filepath: outPath }),
    "utf8",
  );
  console.log(`[generate-bar-types] wrote ${outPath}.`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
