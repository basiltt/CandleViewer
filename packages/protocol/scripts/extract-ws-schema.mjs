#!/usr/bin/env node
// E02-T09: extracts the JSON Schema fenced code blocks from
// docs/plan/23-ws-protocol.md §13-15 (control frames, public payloads,
// private payloads) into a single machine-readable artefact,
// docs/plan/ws-schema.json. The markdown stays human-authoritative; this
// file is machine-authoritative and the two are bound by a drift test
// (packages/protocol/test/ws-schema-drift.test.ts) — same pattern as the
// E02-T06 §3 manifest binding.
//
// It also extracts the §6 topic catalogue (topic -> payload schema $id)
// so the drift test can assert every catalogued topic has a schema.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(__dirname, "..", "..", "..");
const WS_DOC = join(REPO_ROOT, "docs", "plan", "23-ws-protocol.md");
const OUT_FILE = join(REPO_ROOT, "docs", "plan", "ws-schema.json");

/** Extracts every ```json ... ``` fenced block from the markdown source. */
export function extractJsonFences(markdown) {
  const fences = [];
  const re = /```json\r?\n([\s\S]*?)\r?\n```/g;
  let m;
  while ((m = re.exec(markdown)) !== null) {
    fences.push(m[1]);
  }
  return fences;
}

/** Parses fences that look like a JSON Schema (have a `$id`) into a map keyed by $id. */
export function buildSchemaMap(markdown) {
  const schemas = {};
  for (const raw of extractJsonFences(markdown)) {
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch {
      continue; // worked-example payload, not a schema — skip
    }
    if (parsed && typeof parsed === "object" && typeof parsed.$id === "string") {
      schemas[parsed.$id] = parsed;
    }
  }
  return schemas;
}

/**
 * Parses the §6 topic catalogue tables (6.1 public, 6.2 private) into
 * `{ topic, payloadSchemaRef }` rows. Only rows with a resolvable schema
 * link (either a markdown anchor `[Name](#anchor)` or a bare schema name)
 * are extracted; free-text cells ("—", batched variants) are best-effort.
 */
export function extractTopicCatalogue(markdown) {
  const startIdx = markdown.indexOf("## 6. Topic catalogue");
  const endIdx = markdown.indexOf("## 7. Snapshot");
  if (startIdx === -1 || endIdx === -1) {
    throw new Error("Could not locate §6 Topic catalogue / §7 boundary in 23-ws-protocol.md");
  }
  const section = markdown.slice(startIdx, endIdx);
  const rows = [];
  // Every catalogue row is a `| ... | ... |` table line whose first cell is
  // a back-ticked topic pattern. The payload column (last cell) may contain
  // one or two schema names as markdown links or bare identifiers, "✖", or
  // "—" (no payload, e.g. a snapshot-only implicit topic).
  const rowRe = /^\|\s*`([^`]+)`\s*\|(.*)\|\s*$/gm;
  let m;
  while ((m = rowRe.exec(section)) !== null) {
    const topic = m[1];
    const restCells = m[2].split("|");
    const payloadCell = restCells[restCells.length - 1];
    const payloadNames = [...payloadCell.matchAll(/`?([A-Z][A-Za-z]+)`?/g)].map((x) => x[1]);
    if (payloadNames.length === 0) continue;
    for (const payloadSchemaName of payloadNames) {
      rows.push({ topic, payloadSchemaName });
    }
  }
  return rows;
}

function main() {
  const markdown = readFileSync(WS_DOC, "utf8");
  const schemas = buildSchemaMap(markdown);
  const topics = extractTopicCatalogue(markdown);

  const artefact = {
    $schema: "https://json-schema.org/draft/2020-12/schema",
    generatedFrom: "docs/plan/23-ws-protocol.md §13-15 (schemas), §6 (topic catalogue)",
    generatedBy: "packages/protocol/scripts/extract-ws-schema.mjs",
    schemaCount: Object.keys(schemas).length,
    schemas,
    topics,
  };

  writeFileSync(OUT_FILE, JSON.stringify(artefact, null, 2) + "\n", "utf8");
  console.log(
    `[extract-ws-schema] wrote ${OUT_FILE} (${artefact.schemaCount} schemas, ${topics.length} topic rows)`,
  );
}

main();
