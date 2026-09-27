#!/usr/bin/env node
// Recomputes packages/protocol/src/generated/.manifest.json — the sha256 of
// every file under src/generated/ (except the manifest itself), keyed by its
// path relative to src/generated/. Consumed by check-generated-guard.mjs.
import { readFileSync, writeFileSync, readdirSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const generatedDir = join(__dirname, "..", "src", "generated");
const manifestPath = join(generatedDir, ".manifest.json");

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
  const normalised = content.split("\r\n").join("\n");
  return createHash("sha256").update(normalised).digest("hex");
}

function main() {
  const files = listFiles(generatedDir).sort();
  const manifest = {};
  for (const file of files) {
    const rel = relative(generatedDir, file).replace(/\\/g, "/");
    manifest[rel] = sha256(readFileSync(file, "utf8"));
  }
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + "\n", "utf8");
  console.log(`[update-manifest] wrote ${manifestPath} (${files.length} file(s)).`);
}

main();
