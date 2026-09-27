#!/usr/bin/env node
// E02-T09: Python side of the codegen pipeline. Generates pydantic v2
// models from the same two contract inputs the TS side uses, so backend and
// frontend cannot disagree:
//   - services/api/candleviewer/api/_generated/rest_models.py  (from 22-api-openapi.yaml)
//   - services/api/candleviewer/ws/_generated/ws_models.py     (from docs/plan/ws-schema.json)
//
// Money/size/price fields (OpenAPI `Decimal` schema / WS `$defs/decimal`)
// generate as `string` in TS (see generate.mjs) and as a `Decimal`-backed
// type in Python — never `float` — per convention C6. datamodel-code-generator
// emits a `Decimal(RootModel[str])` wrapper for the OpenAPI `Decimal` schema;
// this script rewrites that one wrapper class to a `NewType` over
// `decimal.Decimal` so `mypy --strict` and pydantic both see arbitrary-
// precision decimal arithmetic, not a string, while JSON on the wire is
// still the string convention C6 requires (a `BeforeValidator`/`PlainSerializer`
// pair round-trips it).
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync, existsSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(__dirname, "..", "..", "..");
const API_DIR = join(REPO_ROOT, "services", "api");
const REST_OUT_DIR = join(API_DIR, "candleviewer", "api", "_generated");
const WS_OUT_DIR = join(API_DIR, "candleviewer", "ws", "_generated");

const HEADER = `# ==========================================================================
# GENERATED FILE — DO NOT EDIT BY HAND.
# Regenerate with \`pnpm generate\` (see docs/plan/22-api-openapi.yaml,
# docs/plan/23-ws-protocol.md / docs/plan/ws-schema.json). Hand edits are
# rejected by the header-guard lint (packages/protocol/scripts/check-
# generated-guard.mjs pattern; Python-side guard: this header + CI diff).
# Generator: datamodel-code-generator (pydantic_v2.BaseModel), pinned in
# services/api/pyproject.toml [dependency-groups.dev].
# ==========================================================================
`;

function run(args) {
  return execFileSync("uv", ["run", "--project", API_DIR, "datamodel-codegen", ...args], {
    encoding: "utf8",
    cwd: REPO_ROOT,
  });
}

/**
 * Rewrites the generated `class Decimal(RootModel[str])` wrapper (present
 * whenever the input declares the shared `Decimal` schema) into a
 * `decimal.Decimal`-backed annotated type, so every money/size/price field
 * that referenced it is a real Decimal in Python while still validating and
 * serialising as a decimal string on the wire (C6).
 */
function rewriteDecimalWrapper(source) {
  const classRe = /class Decimal\(RootModel\[str\]\):\r?\n(?:.*\r?\n)*?(?=\r?\n\r?\nclass |$)/;
  if (!classRe.test(source)) return source; // schema had no shared `decimal` $def to wrap
  const replacement = `def _cv_parse_decimal(v: object) -> object:
    """Parses a wire-format decimal string; pydantic wraps a raised ValueError
    into its own ValidationError (a bare decimal.InvalidOperation would not
    be recognised as a validation failure and would propagate as a 500)."""
    if not isinstance(v, str):
        return v
    try:
        return PyDecimal(v)
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal string: {v!r}") from exc


Decimal = Annotated[
    PyDecimal,
    BeforeValidator(_cv_parse_decimal),
    PlainSerializer(lambda v: format(v, "f"), return_type=str),
]
"""Arbitrary-precision decimal transported as a string (convention C6)."""

`;
  let out = source.replace(classRe, replacement);
  out = out.replace(
    /from __future__ import annotations\r?\n/,
    "from __future__ import annotations\n\nfrom decimal import Decimal as PyDecimal\nfrom decimal import InvalidOperation\nfrom typing import Annotated\n\nfrom pydantic import BeforeValidator, PlainSerializer\n",
  );
  return out;
}

function writeGenerated(dir, filename, content) {
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, filename), HEADER + content, "utf8");
  const initFile = join(dir, "__init__.py");
  if (!existsSync(initFile)) {
    writeFileSync(
      initFile,
      HEADER + `"""Generated pydantic models — see ${filename}. Do not hand-edit."""\n`,
      "utf8",
    );
  }
}

function generateRest() {
  const specPath = join(REPO_ROOT, "docs", "plan", "22-api-openapi.yaml");
  const tmpOut = join(REST_OUT_DIR, "_tmp_rest_models.py");
  run([
    "--input",
    specPath,
    "--input-file-type",
    "openapi",
    "--output",
    tmpOut,
    "--output-model-type",
    "pydantic_v2.BaseModel",
    "--target-python-version",
    "3.12",
    "--use-standard-collections",
    "--use-union-operator",
    "--field-constraints",
    "--collapse-root-models",
    "--disable-timestamp",
    "--use-schema-description",
  ]);
  const raw = readFileSync(tmpOut, "utf8");
  rmSync(tmpOut);
  const rewritten = rewriteDecimalWrapper(stripGeneratorBanner(raw));
  writeGenerated(REST_OUT_DIR, "rest_models.py", rewritten);
}

function generateWs() {
  const wsSchemaPath = join(REPO_ROOT, "docs", "plan", "ws-schema.json");
  const artefact = JSON.parse(readFileSync(wsSchemaPath, "utf8"));
  // datamodel-code-generator's JSON Schema mode takes one root document; we
  // hand it a synthetic bundle of all WS schemas as `$defs` under one root
  // so every message kind/topic payload becomes one pydantic model, and
  // `$ref: cv://...` resolves locally without a network fetch.
  const bundle = {
    $schema: "https://json-schema.org/draft/2020-12/schema",
    $id: "cv://ws/v1/_bundle.schema.json",
    $defs: {},
  };
  for (const [id, schema] of Object.entries(artefact.schemas)) {
    const key = id.replace("cv://ws/v1/", "").replace(".schema.json", "");
    bundle.$defs[key] = rewriteInternalRefs(schema, key);
  }
  bundle.oneOf = Object.keys(bundle.$defs).map((k) => ({ $ref: `#/$defs/${k}` }));

  const tmpSchema = join(WS_OUT_DIR, "_tmp_bundle.schema.json");
  mkdirSync(WS_OUT_DIR, { recursive: true });
  writeFileSync(tmpSchema, JSON.stringify(bundle, null, 2), "utf8");

  const tmpOut = join(WS_OUT_DIR, "_tmp_ws_models.py");
  run([
    "--input",
    tmpSchema,
    "--input-file-type",
    "jsonschema",
    "--output",
    tmpOut,
    "--output-model-type",
    "pydantic_v2.BaseModel",
    "--target-python-version",
    "3.12",
    "--use-standard-collections",
    "--use-union-operator",
    "--field-constraints",
    "--collapse-root-models",
    "--disable-timestamp",
  ]);
  const raw = readFileSync(tmpOut, "utf8");
  rmSync(tmpOut);
  rmSync(tmpSchema);
  writeGenerated(WS_OUT_DIR, "ws_models.py", rewriteDecimalWrapper(stripGeneratorBanner(raw)));
}

/**
 * Rewrites `$ref`s in a WS schema for bundling under `$defs/<ownKey>/...`:
 *   - `cv://ws/v1/xxx.schema.json#/...` (cross-document) -> `#/$defs/xxx/...`
 *   - `#/$defs/...` (same-document, e.g. common.schema.json's internal refs
 *     to its own `errorCode`/`seq`/etc.) -> `#/$defs/<ownKey>/$defs/...`
 */
function rewriteInternalRefs(node, ownKey) {
  if (Array.isArray(node)) return node.map((n) => rewriteInternalRefs(n, ownKey));
  if (node && typeof node === "object") {
    const out = {};
    for (const [k, v] of Object.entries(node)) {
      if (k === "$ref" && typeof v === "string" && v.startsWith("cv://ws/v1/")) {
        const [file, fragment = ""] = v.replace("cv://ws/v1/", "").split("#");
        const key = file.replace(".schema.json", "");
        out[k] = `#/$defs/${key}${fragment}`;
      } else if (k === "$ref" && typeof v === "string" && v.startsWith("#/$defs/")) {
        out[k] = `#/$defs/${ownKey}/${v.slice(2)}`;
      } else if (k === "$id" || k === "$schema") {
        continue; // nested $id/$schema confuse the bundler; only the bundle root needs them
      } else {
        out[k] = rewriteInternalRefs(v, ownKey);
      }
    }
    return out;
  }
  return node;
}

/** datamodel-code-generator's own `# generated by ...` banner is replaced by our HEADER. */
function stripGeneratorBanner(source) {
  return source.replace(/^# generated by datamodel-codegen:\r?\n(?:#.*\r?\n)*\r?\n?/, "");
}

function main() {
  generateRest();
  generateWs();
  console.log("[generate-python] wrote rest_models.py and ws_models.py.");
}

main();
