// E17-T02 follow-up (#2042 part A): a decoded binary frame mapped by toStructured() equals the
// §14 JSON twin the Python encoder side renders (packages/fixtures/golden/cvwb/structured.json).
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  decodeBars,
  decodeBookDelta,
  decodeBookSnapshot,
  decodeFootprint,
  decodeHeatmapColumn,
  decodeTrades,
  toStructured,
} from "../src/runtime/index.js";

const dir = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "fixtures", "golden", "cvwb");
const read = <T>(f: string): T => JSON.parse(readFileSync(join(dir, f), "utf8")) as T;
const vectors = read<{ name: string; hex: string; body_kind: number }[]>("vectors.json");
const twins = read<{ name: string; body_kind: number; structured: unknown }[]>("structured.json");

const decoders = [
  decodeBookSnapshot,
  decodeBookDelta,
  decodeTrades,
  decodeBars,
  decodeFootprint,
  decodeHeatmapColumn,
];

/** JSON has no bigint: the twin carries 64-bit integers as strings (precision above 2**53). */
const jsonSafe = (v: unknown): unknown =>
  JSON.parse(JSON.stringify(v, (_k, x: unknown) => (typeof x === "bigint" ? x.toString() : x)));

describe("toStructured() equals the §14 JSON twin", () => {
  it("has a twin for every vector and covers all six kinds", () => {
    expect(twins.map((t) => t.name)).toEqual(vectors.map((v) => v.name));
    expect(new Set(twins.map((t) => t.body_kind))).toEqual(new Set([1, 2, 3, 4, 5, 6]));
  });
  it.each(vectors.map((v, i) => [v.name, v, twins[i]!] as const))("%s", (_n, v, twin) => {
    const decode = decoders[v.body_kind - 1]!;
    const buf = Uint8Array.from(Buffer.from(v.hex, "hex"));
    expect(jsonSafe(toStructured(decode(buf)))).toEqual(twin.structured);
  });
  it("emits prices and sizes as exact decimal strings, never numbers", () => {
    const v = vectors.find((x) => x.body_kind === 3)!;
    const s = toStructured(decodeTrades(Uint8Array.from(Buffer.from(v.hex, "hex"))));
    for (const t of (s as { trades: unknown }).trades as { price: unknown; size: unknown }[]) {
      expect(t.price).toMatch(/^-?[0-9]+(\.[0-9]+)?$/);
      expect(t.size).toMatch(/^-?[0-9]+(\.[0-9]+)?$/);
    }
  });
});
