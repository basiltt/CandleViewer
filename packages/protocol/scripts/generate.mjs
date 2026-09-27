#!/usr/bin/env node
// E02-T09: `pnpm generate` pipeline for @candleviewer/protocol.
//
// Produces (all under src/generated/, all carrying the DO-NOT-EDIT header
// and covered by scripts/check-generated-guard.mjs + generated.manifest.json):
//   - rest.ts        TS types for every OpenAPI schema/operation (openapi-typescript)
//   - ws.ts          TS types for the WS envelope + every message kind/topic payload
//                     (compiled from docs/plan/ws-schema.json via json-schema-to-typescript)
//   - index.ts       barrel re-exporting rest.ts + ws.ts
//
// Also regenerates docs/plan/ws-schema.json (extract-ws-schema.mjs) and the
// Python side (services/api/candleviewer/api/_generated, .../ws/_generated)
// via datamodel-code-generator, so backend and frontend cannot disagree
// (see generate-python.mjs).
//
// `--check` mode runs the same pipeline into a temp directory and diffs it
// against the committed output instead of overwriting it — this is the
// `generate:check` task the staleness gate (`make gen && git diff --exit-code`)
// wraps for CI.
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createHash } from "node:crypto";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PKG_ROOT = join(__dirname, "..");
const REPO_ROOT = join(PKG_ROOT, "..", "..");
const GENERATED_DIR = join(PKG_ROOT, "src", "generated");
const CHECK_MODE = process.argv.includes("--check");

const HEADER = `// ==========================================================================
// GENERATED FILE — DO NOT EDIT BY HAND.
// Regenerate with \`pnpm generate\` (see docs/plan/22-api-openapi.yaml,
// docs/plan/23-ws-protocol.md). Hand edits are rejected by the header-guard
// lint (packages/protocol/scripts/check-generated-guard.mjs) and by
// \`linguist-generated\` in .gitattributes.
// ==========================================================================
`;

function run(cmd, args, opts = {}) {
  return execFileSync(cmd, args, { encoding: "utf8", cwd: REPO_ROOT, ...opts });
}

function sha256(content) {
  const normalised = content.split("\r\n").join("\n");
  return createHash("sha256").update(normalised).digest("hex");
}

/** Step 1: extract docs/plan/ws-schema.json from the WS protocol markdown. */
function regenerateWsSchemaJson() {
  run("node", [join(PKG_ROOT, "scripts", "extract-ws-schema.mjs")]);
}

/**
 * Step 3: TS types for the WS envelope + every message-kind/topic payload
 * schema in docs/plan/ws-schema.json, via json-schema-to-typescript.
 *
 * All 34 schemas are bundled into one synthetic root document (`$defs`
 * keyed by short name, e.g. `envelope`, `common`, `sub_ok`), with every
 * `cv://ws/v1/xxx.schema.json` cross-reference and same-document
 * `#/$defs/...` reference rewritten to point at the bundle — this is the
 * same strategy generate-python.mjs uses for the pydantic side, and for the
 * same reason: compiling each schema independently produced duplicate
 * type names (`Options`, `Error`, `KillSwitch`, `Levels`) with no way to
 * merge them, because shared `$defs` (from `common.schema.json`) were
 * re-inlined once per referencing schema instead of resolving to one type.
 */
async function generateWsTypes() {
  const { compile } = await import("json-schema-to-typescript");
  const wsSchemaPath = join(REPO_ROOT, "docs", "plan", "ws-schema.json");
  const artefact = JSON.parse(readFileSync(wsSchemaPath, "utf8"));

  const bundle = { $defs: {}, oneOf: [] };
  for (const id of Object.keys(artefact.schemas).sort()) {
    const key = id.replace("cv://ws/v1/", "").replace(".schema.json", "");
    const schema = { ...artefact.schemas[id] };
    delete schema.title;
    delete schema.$id;
    delete schema.$schema;
    bundle.$defs[key] = rewriteRefsForBundle(schema, key);
    // The `oneOf` (rather than compiling each $defs entry standalone) is
    // what makes json-schema-to-typescript treat every key as externally
    // referenced and hoist it to a top-level named export instead of
    // inlining it once per referencing schema — which previously produced
    // duplicate, un-mergeable `Options`/`Error`/`KillSwitch`/`Levels` types
    // (one copy per schema that referenced `common.schema.json`).
    bundle.oneOf.push({ $ref: `#/$defs/${key}` });
  }

  const ts = await compile(bundle, "WsBundle", {
    cwd: REPO_ROOT,
    bannerComment: "",
    style: { semi: true, singleQuote: false },
    declareExternallyReferenced: true,
  });

  const renamed = renameWsBundleExports(ts, Object.keys(bundle.$defs));

  return (
    HEADER +
    "// Source: docs/plan/23-ws-protocol.md §13-15 (schemas), extracted to\n" +
    "// docs/plan/ws-schema.json by packages/protocol/scripts/extract-ws-schema.mjs.\n" +
    "// Generator: json-schema-to-typescript (deterministic; one shared $defs bundle).\n\n" +
    renamed
  );
}

/** Rewrites `$ref`s for the single-document bundle (see generate-python.mjs's twin). */
function rewriteRefsForBundle(node, ownKey) {
  if (Array.isArray(node)) return node.map((n) => rewriteRefsForBundle(n, ownKey));
  if (node && typeof node === "object") {
    const out = {};
    for (const [k, v] of Object.entries(node)) {
      if (k === "$ref" && typeof v === "string" && v.startsWith("cv://ws/v1/")) {
        const [file, fragment = ""] = v.replace("cv://ws/v1/", "").split("#");
        out[k] = `#/$defs/${file.replace(".schema.json", "")}${fragment}`;
      } else if (k === "$ref" && typeof v === "string" && v.startsWith("#/$defs/")) {
        out[k] = `#/$defs/${ownKey}/${v.slice(2)}`;
      } else if (k === "$id" || k === "$schema") {
        continue;
      } else {
        out[k] = rewriteRefsForBundle(v, ownKey);
      }
    }
    return out;
  }
  return node;
}

function toPascal(key) {
  return key
    .split(/[_\-.]/)
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join("");
}

/**
 * json-schema-to-typescript names each hoisted `$defs` entry after its own
 * JSON Pointer segment, PascalCased (e.g. `auth_ok` -> `AuthOk`) — this
 * includes both the 34 top-level bundle keys (`keys`) *and* any nested
 * shared `$defs` it separately hoists (e.g. `KillSwitch`, `Options`, `Error`
 * from `common.schema.json`, whose pointer segment doesn't match a bundle
 * key). Scanning the compiled output's own top-level export names (rather
 * than only `keys`) prefixes every one of those with `Ws` too — critical for
 * `Error`, which otherwise shadows the global `Error` type — and drops the
 * empty `WsBundle` root type the `oneOf` wrapper itself produces.
 */
function renameWsBundleExports(ts, keys) {
  const exportedNames = [...ts.matchAll(/^export (?:interface|type) ([A-Za-z0-9_]+)/gm)].map(
    (m) => m[1],
  );
  const names = [...new Set([...keys.map(toPascal), ...exportedNames])]
    .filter((n) => n !== "Levels" && n !== "Levels1" && n !== "WsBundle")
    .sort((a, b) => b.length - a.length);
  let out = ts;
  for (const name of names) {
    out = out.replace(new RegExp(`\\b${name}\\b`, "g"), `Ws${name}`);
  }
  out = out.replace(/export (?:interface|type) WsWsBundle[\s\S]*?(?:\n\}\n|;\n)/, "");
  return out.trim() + "\n";
}

function generateRestTypes(outDir) {
  const specPath = join(REPO_ROOT, "docs", "plan", "22-api-openapi.yaml");
  const cliEntry = join(PKG_ROOT, "node_modules", "openapi-typescript", "bin", "cli.js");
  const outFile = join(outDir, "_rest.raw.ts");
  run("node", [cliEntry, specPath, "-o", outFile, "--root-types"]);
  const body = readFileSync(outFile, "utf8");
  rmSync(outFile);
  return (
    HEADER +
    "// Source: docs/plan/22-api-openapi.yaml (conventions C1-C10).\n" +
    "// Generator: openapi-typescript (deterministic, pinned; no runtime client emitted).\n\n" +
    body
  );
}

function barrel() {
  return (
    HEADER +
    "// Barrel: re-exports the OpenAPI-derived REST types and the WS protocol\n" +
    "// types. Both are consumed via `@candleviewer/protocol` (src/index.ts) —\n" +
    "// never import these generated files directly from app code.\n" +
    'export * as rest from "./rest.js";\n' +
    'export * as ws from "./ws.js";\n'
  );
}

function writeManifest(files) {
  const manifest = {};
  for (const [name, content] of files) {
    manifest[name] = sha256(content);
  }
  writeFileSync(
    join(GENERATED_DIR, ".manifest.json"),
    JSON.stringify(manifest, null, 2) + "\n",
    "utf8",
  );
}

/** Regenerates the Python-side pydantic models (delegated — see generate-python.mjs). */
function generatePython() {
  run("node", [join(__dirname, "generate-python.mjs")]);
}

async function main() {
  regenerateWsSchemaJson();

  const restTs = generateRestTypes(GENERATED_DIR);
  const wsTs = await generateWsTypes();
  const indexTs = barrel();

  const files = [
    ["rest.ts", restTs],
    ["ws.ts", wsTs],
    ["index.ts", indexTs],
  ];

  if (CHECK_MODE) {
    const stagingDir = mkdtempSync(join(tmpdir(), "cv-protocol-gen-"));
    try {
      for (const [name, content] of files) {
        writeFileSync(join(stagingDir, name), content, "utf8");
      }
      let stale = false;
      for (const [name, content] of files) {
        const committedPath = join(GENERATED_DIR, name);
        const committed = existsSync(committedPath) ? readFileSync(committedPath, "utf8") : null;
        if (committed !== content) {
          stale = true;
          console.error(
            `[generate:check] STALE: src/generated/${name} does not match a fresh run.`,
          );
        }
      }
      if (stale) {
        console.error("[generate:check] Run `pnpm generate` (or `make gen`) and commit the diff.");
        process.exitCode = 1;
        return;
      }
      console.log("[generate:check] OK — generated output is up to date.");
    } finally {
      rmSync(stagingDir, { recursive: true, force: true });
    }
    return;
  }

  mkdirSync(GENERATED_DIR, { recursive: true });
  for (const [name, content] of files) {
    writeFileSync(join(GENERATED_DIR, name), content, "utf8");
  }
  writeManifest(files);
  generatePython();
  console.log(
    `[generate] wrote ${files.length} file(s) to src/generated/ and regenerated the Python side.`,
  );
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
