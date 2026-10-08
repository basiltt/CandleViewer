#!/usr/bin/env node
// E17-T02: compiles the ONE CVWB layout declaration (packages/protocol/cvwb-layout.json,
// docs/plan/23-ws-protocol.md §3.4) into
//   - src/generated/cvwb/index.ts                        (TS decoder offsets/strides)
//   - services/api/candleviewer/ws/_generated/cvwb_layout.py (Python struct formats)
// Strides are recomputed from the field list and must equal the declared
// `record_bytes`; any mismatch aborts generation. Deterministic, no deps.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import prettier from "prettier";

const __dirname = dirname(fileURLToPath(import.meta.url));
const pkgRoot = join(__dirname, "..");
const repoRoot = join(pkgRoot, "..", "..");
const layoutPath = join(pkgRoot, "cvwb-layout.json");
const tsOut = join(pkgRoot, "src", "generated", "cvwb", "index.ts");
const pyOut = join(
  repoRoot,
  "services",
  "api",
  "candleviewer",
  "ws",
  "_generated",
  "cvwb_layout.py",
);

const SIZE = { u8: 1, u32: 4, u64: 8, i64: 8, pad3: 3, pad4: 4 };
const FMT = { u8: "B", u32: "I", u64: "Q", i64: "q", pad3: "3x", pad4: "4x" };

function walk(fields, where) {
  const offsets = {};
  let off = 0;
  for (const f of fields) {
    const size = SIZE[f.type];
    if (size === undefined) throw new Error(`${where}.${f.name}: unknown type ${f.type}`);
    if (!f.type.startsWith("pad")) offsets[f.name] = off;
    off += size;
  }
  const fmt = "<" + fields.map((f) => FMT[f.type]).join("");
  const real = fields.filter((f) => !f.type.startsWith("pad"));
  const names = real.map((f) => f.name);
  const types = Object.fromEntries(real.map((f) => [f.name, f.type]));
  const enums = Object.fromEntries(real.filter((f) => f.enum).map((f) => [f.name, f.enum]));
  return { offsets, size: off, fmt, names, types, enums };
}

function compileLayout(doc) {
  const header = walk(doc.header, "header");
  if (header.size !== doc.header_bytes) {
    throw new Error(`header is ${header.size} bytes, declared ${doc.header_bytes}`);
  }
  const kinds = doc.kinds.map((k) => {
    const record = walk(k.record, `${k.name}.record`);
    if (record.size !== k.record_bytes) {
      throw new Error(`${k.name}: fields sum to ${record.size}, declared ${k.record_bytes}`);
    }
    const out = {
      id: k.id,
      name: k.name,
      formatVersion: k.format_version,
      lengthRule: k.length_rule,
      record,
    };
    for (const part of ["trailer", "group_prefix", "body_prefix"]) {
      if (k[part]) out[part] = walk(k[part], `${k.name}.${part}`);
    }
    return out;
  });
  return { magic: doc.magic, header, flags: doc.header_flags, kinds };
}

const TS_HEADER = `// ==========================================================================
// GENERATED FILE — DO NOT EDIT BY HAND.
// Regenerate with \`pnpm --filter @candleviewer/protocol generate\`.
// Source: packages/protocol/cvwb-layout.json (docs/plan/23-ws-protocol.md §3.4)
// via scripts/generate-cvwb-layout.mjs. The Python twin is
// services/api/candleviewer/ws/_generated/cvwb_layout.py (same generator).
// ==========================================================================
/* eslint-disable */
`;

function camel(name) {
  return name.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
}

function tsPart(p) {
  const offs = Object.entries(p.offsets)
    .map(([n, o]) => `${camel(n)}: ${o}`)
    .join(", ");
  const types = Object.entries(p.types)
    .map(([n, t]) => `${camel(n)}: "${t}"`)
    .join(", ");
  return `{ bytes: ${p.size}, offsets: { ${offs} }, types: { ${types} } }`;
}

function renderTs(c) {
  const lines = [TS_HEADER];
  lines.push(`export const CVWB_MAGIC = ${c.magic};`);
  lines.push(`export const CVWB_HEADER = ${tsPart(c.header)} as const;`);
  const flags = c.flags.map((f, i) => `${camel(f)}: ${1 << i}`).join(", ");
  lines.push(`export const CVWB_HEADER_FLAGS = { ${flags} } as const;`);
  lines.push(`export const CVWB_KINDS = {`);
  for (const k of c.kinds) {
    const parts = [
      `id: ${k.id}`,
      `formatVersion: ${k.formatVersion}`,
      `lengthRule: "${k.lengthRule}"`,
      `record: ${tsPart(k.record)}`,
    ];
    if (k.trailer) parts.push(`trailer: ${tsPart(k.trailer)}`);
    if (k.group_prefix) parts.push(`groupPrefix: ${tsPart(k.group_prefix)}`);
    if (k.body_prefix) parts.push(`bodyPrefix: ${tsPart(k.body_prefix)}`);
    lines.push(`  ${camel(k.name)}: { ${parts.join(", ")} },`);
  }
  lines.push(`} as const;`, "");
  return lines.join("\n");
}

function pyPart(p) {
  const offs = Object.entries(p.offsets)
    .map(([n, o]) => `"${n}": ${o}`)
    .join(", ");
  const names = p.names.map((n) => `"${n}"`).join(", ");
  const enums = Object.entries(p.enums)
    .map(([n, vs]) => `"${n}": (${vs.join(", ")}${vs.length === 1 ? "," : ""})`)
    .join(", ");
  return `Part(${p.size}, "${p.fmt}", (${names}${p.names.length === 1 ? "," : ""}), {${offs}}, {${enums}})`;
}

function renderPy(c) {
  const out = [
    '"""GENERATED FILE - DO NOT EDIT BY HAND.',
    "",
    "Generator: packages/protocol/scripts/generate-cvwb-layout.mjs (E17-T02).",
    "Source: packages/protocol/cvwb-layout.json (docs/plan/23-ws-protocol.md section 3.4).",
    "Run `pnpm --filter @candleviewer/protocol generate`.",
    '"""',
    "",
    "from __future__ import annotations",
    "",
    "from typing import Final, NamedTuple",
    "",
    "",
    "class Part(NamedTuple):",
    "    size: int",
    "    fmt: str",
    "    fields: tuple[str, ...]",
    "    offsets: dict[str, int]",
    "    enums: dict[str, tuple[int, ...]]",
    "",
    "",
    "class Kind(NamedTuple):",
    "    id: int",
    "    name: str",
    "    format_version: int",
    "    length_rule: str",
    "    record: Part",
    "    trailer: Part | None",
    "    group_prefix: Part | None",
    "    body_prefix: Part | None",
    "",
    "",
    `MAGIC: Final = ${c.magic}`,
    `HEADER: Final = ${pyPart(c.header)}`,
    `HEADER_FLAGS: Final[tuple[str, ...]] = (${c.flags.map((f) => `"${f}"`).join(", ")})`,
    "KINDS: Final[dict[int, Kind]] = {",
  ];
  for (const k of c.kinds) {
    const opt = (p) => (p ? pyPart(p) : "None");
    out.push(
      `    ${k.id}: Kind(`,
      `        ${k.id},`,
      `        "${k.name}",`,
      `        ${k.formatVersion},`,
      `        "${k.lengthRule}",`,
      `        ${pyPart(k.record)},`,
      `        ${opt(k.trailer)},`,
      `        ${opt(k.group_prefix)},`,
      `        ${opt(k.body_prefix)},`,
      "    ),",
    );
  }
  out.push("}", "");
  return out.join("\n");
}

async function main() {
  const compiled = compileLayout(JSON.parse(readFileSync(layoutPath, "utf8")));
  mkdirSync(dirname(tsOut), { recursive: true });
  const config = (await prettier.resolveConfig(tsOut)) ?? {};
  writeFileSync(
    tsOut,
    await prettier.format(renderTs(compiled), { ...config, filepath: tsOut }),
    "utf8",
  );
  writeFileSync(pyOut, renderPy(compiled), "utf8");
  console.log(`[generate-cvwb-layout] wrote ${tsOut} and ${pyOut}.`);
}

await main();
