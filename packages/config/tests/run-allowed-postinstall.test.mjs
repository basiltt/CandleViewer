import { describe, expect, it } from "vitest";
import { loadAllowlist } from "../../../tools/ci/run-allowed-postinstall.mjs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(fileURLToPath(import.meta.url), "..", "..", "..", "..");

describe("loadAllowlist", () => {
  it("reads the SR-138 exception list and returns package names", () => {
    const names = loadAllowlist(repoRoot);
    expect(names).toEqual(expect.arrayContaining(["electron", "esbuild"]));
    expect(names.length).toBeGreaterThan(0);
  });
});
