// E17-T02 part B: nightly mutation fuzz of the TS CVWB decoders (SR-155), seeded from
// tests/fuzz/ws-frames/corpus.json. Invariant: every decoder returns or throws ONLY
// BinaryFrameError. N via CV_FUZZ_EXAMPLES (default 20 000), seed via CV_FUZZ_SEED.
// Failing inputs go to CV_FUZZ_ARTIFACT_DIR (CI artefact, never the repo).
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";
import {
  BinaryFrameError,
  decodeBars,
  decodeBookDelta,
  decodeBookSnapshot,
  decodeFootprint,
  decodeHeatmapColumn,
  decodeTrades,
} from "../src/runtime/index.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const corpus = JSON.parse(
  readFileSync(join(HERE, "../../../tests/fuzz/ws-frames/corpus.json"), "utf8"),
) as { name: string; hex: string }[];
const SEEDS = corpus.map((s) => Uint8Array.from(Buffer.from(s.hex, "hex")));
const N = Number(process.env["CV_FUZZ_EXAMPLES"] ?? 20_000);
const SEED = Number(process.env["CV_FUZZ_SEED"] ?? 0xc0ffee);
const MAX_HEAP_GROWTH = 256 * 1024 * 1024;
const INTERESTING = [0, 1, 2, 0x7fffffff, 0x80000000, 0xffffffff, 0xfffffffe];
const DECODERS = [
  decodeBookSnapshot,
  decodeBookDelta,
  decodeTrades,
  decodeBars,
  decodeFootprint,
  decodeHeatmapColumn,
];

/** mulberry32: small seeded PRNG so a failing run is reproducible. */
function prng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function mutate(seed: Uint8Array, rnd: () => number): Uint8Array {
  const int = (n: number): number => Math.floor(rnd() * n);
  let buf = Uint8Array.from(seed);
  for (let ops = 1 + int(6); ops > 0; ops--) {
    const kind = int(5);
    if (kind === 1) {
      buf = buf.slice(0, int(buf.length + 1));
    } else if (kind === 3) {
      buf = Uint8Array.from([...buf, ...new Uint8Array(int(65)).fill(int(256))]);
    } else if (buf.length === 0) {
      continue;
    } else if (kind === 0) {
      const at = int(buf.length);
      buf[at] = (buf[at] ?? 0) ^ (1 << int(8));
    } else if (kind === 2) {
      buf[int(buf.length)] = int(256);
    } else if (buf.length >= 4) {
      new DataView(buf.buffer).setUint32(int(buf.length - 3), INTERESTING[int(7)] ?? 0, true);
    }
  }
  return buf;
}

function save(data: Uint8Array): void {
  const dir = process.env["CV_FUZZ_ARTIFACT_DIR"];
  if (!dir) return;
  mkdirSync(dir, { recursive: true });
  const name = Buffer.from(data).toString("hex").slice(0, 40) || "empty";
  writeFileSync(join(dir, `cvwb-ts-fail-${name}.bin`), data);
}

it(`decoders throw only BinaryFrameError over ${N} mutated corpus inputs`, () => {
  const rnd = prng(SEED);
  const heap0 = process.memoryUsage().heapUsed;
  for (let i = 0; i < N; i++) {
    const data = mutate(SEEDS[Math.floor(rnd() * SEEDS.length)] ?? new Uint8Array(0), rnd);
    for (const decode of DECODERS) {
      try {
        decode(data);
      } catch (e) {
        if (!(e instanceof BinaryFrameError)) {
          save(data);
          throw new Error(
            `${decode.name} threw ${String(e)} on ${Buffer.from(data).toString("hex")}`,
          );
        }
      }
    }
  }
  expect(process.memoryUsage().heapUsed - heap0).toBeLessThan(MAX_HEAP_GROWTH);
});
