#!/usr/bin/env node
// Data-ink matrix generator + gate (E47-T03).
//   node tools/contrast/data-ink.mjs          write packages/ui/contrast/data-ink-matrix.{json,md}
//   node tools/contrast/data-ink.mjs --check  fail on a stale checked-in matrix (A11Y-C007)
//                                             or on any failure not in data-ink-baseline.json
//   --stops N                                 gradient samples (integer >= 16)
//   --list-failing                            print failing keys (to seed/trim the baseline)
// The baseline lists known failures awaiting palette retune (E47-S06); it can
// only shrink via reviewed edits. Edits to the checked-in matrix are never hand-made.
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { loadResolvedThemes } from "../../packages/ui/scripts/build-tokens.mjs";
import { CVD_JND_FLOOR } from "./color-math.mjs";
import { CODE, DEFAULT_STOPS, evaluate, summarise, toMarkdown } from "./data-ink-lib.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(__dirname, "..", "..", "packages", "ui", "contrast");
export const MATRIX_JSON = path.join(OUT_DIR, "data-ink-matrix.json");
export const MATRIX_MD = path.join(OUT_DIR, "data-ink-matrix.md");
export const BASELINE_FILE = path.join(__dirname, "data-ink-baseline.json");

export function render(rows, stops) {
  const json =
    JSON.stringify(
      {
        generatedBy: "tools/contrast/data-ink.mjs",
        stops,
        cvdJndFloor: CVD_JND_FLOOR,
        summary: summarise(rows),
        rows,
      },
      null,
      2,
    ) + "\n";
  return { json, md: toMarkdown(rows, stops) };
}

export async function main(argv = process.argv.slice(2)) {
  const check = argv.includes("--check");
  const si = argv.indexOf("--stops");
  const stops = si >= 0 ? Number(argv[si + 1]) : DEFAULT_STOPS;
  if (!Number.isInteger(stops) || stops < 16)
    throw new Error("A11Y-C000 --stops must be an integer >= 16");
  const rows = evaluate(await loadResolvedThemes(), { stops });
  const failing = rows.filter((r) => !r.pass);
  if (argv.includes("--list-failing")) {
    console.log(JSON.stringify(failing.map((r) => r.key).sort(), null, 2));
    return;
  }
  const known = new Set(JSON.parse(await readFile(BASELINE_FILE, "utf-8")).knownFailing);
  const fresh = failing.filter((r) => !known.has(r.key));
  console.log(
    `[data-ink] ${rows.length} checks; failing per theme ${JSON.stringify(summarise(rows).failingPerTheme)}; ` +
      `${failing.length - fresh.length} known (E47-S06), ${fresh.length} new`,
  );
  for (const r of fresh) {
    console.error(`[data-ink] ${CODE[r.kind]} ${r.key}: ${r.ratio ?? r.deltaE} < ${r.threshold}`);
  }
  let bad = fresh.length > 0;
  const { json, md } = render(rows, stops);
  if (check) {
    const cur = await Promise.all(
      [MATRIX_JSON, MATRIX_MD].map((f) => readFile(f, "utf-8").catch(() => "")),
    );
    if (cur[0] !== json || cur[1] !== md) {
      console.error(
        "[data-ink] A11Y-C007 stale checked-in matrix; run `pnpm --filter @candleviewer/ui contrast:data-ink` and commit",
      );
      bad = true;
    }
  } else {
    await mkdir(OUT_DIR, { recursive: true });
    await writeFile(MATRIX_JSON, json, "utf-8");
    await writeFile(MATRIX_MD, md, "utf-8");
  }
  if (bad) process.exitCode = 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((e) => {
    console.error(e.stack ?? e);
    process.exitCode = 1;
  });
}
