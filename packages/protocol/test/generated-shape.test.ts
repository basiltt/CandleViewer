// E02-T09 acceptance: representative generator output must have the right
// shape — Decimal as `string` (never `number`), pagination/problem envelopes
// present, and the full type surface non-empty (contract-consumer sanity).
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const restTs = readFileSync(join(__dirname, "..", "src", "generated", "rest.ts"), "utf8");
const wsTs = readFileSync(join(__dirname, "..", "src", "generated", "ws.ts"), "utf8");

describe("generated REST types (docs/plan/22-api-openapi.yaml)", () => {
  it("represents the shared Decimal schema as a string, never a number (C6)", () => {
    expect(restTs).toMatch(/Decimal:\s*string;/);
    expect(restTs).not.toMatch(/Decimal:\s*number;/);
  });

  it("includes the RFC 9457 Problem envelope", () => {
    expect(restTs).toMatch(/RFC 9457 problem detail/);
  });

  it("includes the pagination envelope (PageMeta)", () => {
    expect(restTs).toMatch(/PageMeta:/);
  });

  it("documents the Idempotency-Key convention for order-mutating requests", () => {
    expect(restTs).toMatch(/Idempotency-Key/);
  });

  it("is non-empty and carries the do-not-edit header", () => {
    expect(restTs).toMatch(/GENERATED FILE — DO NOT EDIT BY HAND/);
    expect(restTs.length).toBeGreaterThan(1000);
  });
});

describe("generated WS types (docs/plan/23-ws-protocol.md §13-15)", () => {
  it("exports every §6 topic payload kind, Ws-prefixed", () => {
    for (const name of [
      "WsEnvelope",
      "WsBars",
      "WsBook",
      "WsTrades",
      "WsOrders",
      "WsPositions",
      "WsWallet",
      "WsExecutions",
      "WsHeatmap",
      "WsFootprint",
    ]) {
      expect(wsTs).toMatch(new RegExp(`export (?:interface|type) ${name}\\b`));
    }
  });

  it("never leaves an un-prefixed name that would shadow a JS/TS global (Error)", () => {
    expect(wsTs).not.toMatch(/export interface Error\b/);
    expect(wsTs).toMatch(/export interface WsError\b/);
  });

  it("is non-empty and carries the do-not-edit header", () => {
    expect(wsTs).toMatch(/GENERATED FILE — DO NOT EDIT BY HAND/);
    expect(wsTs.length).toBeGreaterThan(1000);
  });
});
