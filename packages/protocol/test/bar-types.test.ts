import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { readFileSync, writeFileSync } from "node:fs";
import type { bars } from "../src/generated/index.js";
import type { ws } from "../src/generated/index.js";

// E12-T01: the TS bar model is generated from the Pydantic models (via the committed
// JSON Schema). Regenerating must reproduce the committed file byte-for-byte.

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = join(__dirname, "..");
const outPath = join(packageRoot, "src", "generated", "bars", "index.ts");
const vectorsPath = join(packageRoot, "..", "fixtures", "golden", "bars", "spec_hash_vectors.json");

describe("generated bar types", () => {
  it("match a fresh generation from bar-model.schema.json (drift check)", () => {
    const committed = readFileSync(outPath, "utf8").split("\r\n").join("\n");
    try {
      execFileSync("node", [join(packageRoot, "scripts", "generate-bar-types.mjs")], {
        cwd: packageRoot,
        stdio: "pipe",
      });
      const fresh = readFileSync(outPath, "utf8").split("\r\n").join("\n");
      expect(fresh).toBe(committed);
    } finally {
      writeFileSync(outPath, committed, "utf8");
    }
  });

  it("type every golden spec and a Bar compatible with the BarsBatch wire shape", () => {
    const doc = JSON.parse(readFileSync(vectorsPath, "utf8")) as {
      vectors: { canonical_json: string }[];
    };
    const specs: bars.BarSpec[] = doc.vectors.map((v) => JSON.parse(v.canonical_json));
    expect(specs.length).toBeGreaterThan(0);
    const bar: bars.Bar = {
      spec_hash: "a".repeat(64),
      symbol: "BTCUSDT",
      index: 0,
      open_time: 1_789_132_000_000_000,
      close_time: 1_789_132_060_000_000,
      open: "100",
      high: "101",
      low: "99",
      close: "100.5",
      volume: "3",
      buy_volume: "2",
      sell_volume: "1",
      delta: "1",
      min_delta: "-1",
      max_delta: "2",
      trade_count: 4,
      turnover: "300",
      vwap: "100",
      closed: true,
      partial: false,
      gap_before: false,
    };
    const update: bars.BarUpdate = { kind: "close", bar };
    type WireBar = ws.BarsSymbolBarTypeParam["bars"][number];
    const wire: WireBar = {
      t_ms: Math.floor(bar.open_time / 1000),
      o: bar.open,
      h: bar.high,
      l: bar.low,
      c: bar.close,
      v: bar.volume,
      confirm: update.bar.closed,
    };
    expect(wire.c).toBe("100.5");
  });
});
