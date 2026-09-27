#!/usr/bin/env node
// Runs the chart-engine bench and writes bench/results.json.
// Scaffold (E02-T03): the empty scene always yields zero values; E06/E11 wire
// a real headless-GL scene. Kept dependency-free (no dist/ build required)
// so `pnpm --filter @candleviewer/chart-engine bench` is runnable standalone
// and deterministic, per CONSTITUTION.md §9 #16 / the ticket's acceptance
// criterion (exits 0, writes the four required keys).
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const isBaseline = process.argv.includes("--baseline");
const __dirname = dirname(fileURLToPath(import.meta.url));

const result = {
  frameTimeMs: { p50: 0, p95: 0, p99: 0 },
  drawCalls: 0,
  memoryMb: 0,
};

const outPath = join(__dirname, isBaseline ? "baseline.json" : "results.json");
writeFileSync(outPath, JSON.stringify(result, null, 2) + "\n", "utf8");

console.log(`[bench] wrote ${outPath}`);
