#!/usr/bin/env node
// Generated-file header guard (E02-T03 acceptance criterion #3).
// Every file under src/generated/ must start with the GENERATED FILE header
// and match the recorded manifest hash; a hand edit changes the hash without
// updating the manifest, so this fails and points the author at `pnpm generate`.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const generatedDir = join(__dirname, "..", "src", "generated");
const manifestPath = join(generatedDir, ".manifest.json");
const HEADER_MARKER = "GENERATED FILE — DO NOT EDIT BY HAND";

function listFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    if (entry === ".manifest.json") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...listFiles(full));
    } else {
      out.push(full);
    }
  }
  return out;
}

function sha256(content) {
  // Line-ending agnostic: a Windows checkout may present CRLF while the manifest
  // was recorded from LF content. Only bytes, never EOL style, decide "hand-edited".
  const normalised = content.split("\r\n").join("\n");
  return createHash("sha256").update(normalised).digest("hex");
}

function main() {
  const files = listFiles(generatedDir);
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  const errors = [];

  for (const file of files) {
    const rel = relative(generatedDir, file).replace(/\\/g, "/");
    const content = readFileSync(file, "utf8");
    if (!content.includes(HEADER_MARKER)) {
      errors.push(`${rel}: missing the "${HEADER_MARKER}" header.`);
      continue;
    }
    const expected = manifest[rel];
    const actual = sha256(content);
    if (!expected) {
      errors.push(`${rel}: not in .manifest.json — run \`pnpm generate\` to regenerate.`);
    } else if (expected !== actual) {
      errors.push(
        `${rel}: hash mismatch (hand-edited?). Run \`pnpm generate\` instead of editing generated files.`,
      );
    }
  }

  if (errors.length > 0) {
    console.error("[generated-guard] FAILED:\n" + errors.map((e) => `  - ${e}`).join("\n"));
    process.exit(1);
  }
  console.log(`[generated-guard] OK (${files.length} file(s) verified against manifest).`);
}

main();
