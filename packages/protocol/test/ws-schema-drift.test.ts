import { describe, expect, it, afterEach } from "vitest";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { readFileSync, writeFileSync, rmSync } from "node:fs";

// This test binds docs/plan/ws-schema.json (machine-authoritative) to
// docs/plan/23-ws-protocol.md (human-authoritative) — the "doc-drift" pattern
// required by E02-T09 AC4 and documented at the top of
// scripts/extract-ws-schema.mjs. It must fail whenever the committed
// artefact disagrees with a fresh extraction of the markdown, and whenever
// the markdown's §6 topic catalogue names a topic the schema doesn't cover.

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = join(__dirname, "..");
const repoRoot = join(packageRoot, "..", "..");
const extractScript = join(packageRoot, "scripts", "extract-ws-schema.mjs");
const schemaPath = join(repoRoot, "docs", "plan", "ws-schema.json");

let backup: string | undefined;

afterEach(() => {
  if (backup !== undefined) {
    writeFileSync(schemaPath, backup, "utf8");
    backup = undefined;
  }
});

describe("ws-schema.json drift", () => {
  it("matches a fresh extraction of docs/plan/23-ws-protocol.md", () => {
    expect(() =>
      execFileSync("node", [extractScript, "--check"], { cwd: packageRoot, stdio: "pipe" }),
    ).not.toThrow();
  });

  it("fails --check when the committed artefact is hand-edited out of sync", () => {
    backup = readFileSync(schemaPath, "utf8");
    const tampered = backup.replace('"schemaCount":', '"schemaCount_TAMPERED":');
    writeFileSync(schemaPath, tampered, "utf8");

    expect(() =>
      execFileSync("node", [extractScript, "--check"], { cwd: packageRoot, stdio: "pipe" }),
    ).toThrow();
  });

  it("fails --check when the markdown's §6 topic catalogue gains a row missing from the artefact", () => {
    // Simulates AC4: a new topic row in 23-ws-protocol.md that the committed
    // ws-schema.json does not yet know about. We can't (and mustn't) hand-edit
    // the markdown here, so we assert the mechanism directly: removing a known
    // topic row from the committed artefact must reproduce the same failure
    // mode --check reports for "markdown row present, artefact row absent".
    backup = readFileSync(schemaPath, "utf8");
    const artefact = JSON.parse(backup) as { topicCatalogue: Array<{ topicPattern: string }> };
    expect(artefact.topicCatalogue.length).toBeGreaterThan(0);
    artefact.topicCatalogue.pop();
    writeFileSync(schemaPath, JSON.stringify(artefact, null, 2) + "\n", "utf8");

    expect(() =>
      execFileSync("node", [extractScript, "--check"], { cwd: packageRoot, stdio: "pipe" }),
    ).toThrow();
  });
});
