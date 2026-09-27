// E02-T09 acceptance criterion: docs/plan/ws-schema.json (machine-readable)
// must never drift from docs/plan/23-ws-protocol.md (human-authoritative).
// This binds the two: re-extract from the markdown and diff against the
// committed artefact, and assert every §6 catalogued topic has a schema.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
// @ts-expect-error -- plain .mjs script, no type declarations (not part of the published package surface)
import { buildSchemaMap, extractTopicCatalogue } from "../scripts/extract-ws-schema.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(__dirname, "..", "..", "..");
const WS_DOC = join(REPO_ROOT, "docs", "plan", "23-ws-protocol.md");
const WS_SCHEMA_JSON = join(REPO_ROOT, "docs", "plan", "ws-schema.json");

describe("ws-schema.json drift (docs/plan/23-ws-protocol.md is authoritative)", () => {
  const markdown = readFileSync(WS_DOC, "utf8");
  const committed = JSON.parse(readFileSync(WS_SCHEMA_JSON, "utf8"));

  it("has a schemaCount matching a fresh extraction from the markdown", () => {
    const fresh = buildSchemaMap(markdown);
    expect(committed.schemaCount).toBe(Object.keys(fresh).length);
    expect(Object.keys(committed.schemas).sort()).toEqual(Object.keys(fresh).sort());
  });

  it("has every §6-catalogued topic mapped to at least one schema name", () => {
    const freshTopics = extractTopicCatalogue(markdown);
    expect(freshTopics.length).toBeGreaterThan(0);
    expect(committed.topics).toEqual(freshTopics);
    for (const row of freshTopics) {
      expect(row.payloadSchemaName).toMatch(/^[A-Z][A-Za-z]+$/);
    }
  });

  it("is not stale relative to a from-scratch re-extraction (full artefact diff)", () => {
    const fresh = {
      schemas: buildSchemaMap(markdown),
      topics: extractTopicCatalogue(markdown),
    };
    expect(committed.schemas).toEqual(fresh.schemas);
    expect(committed.topics).toEqual(fresh.topics);
  });
});
