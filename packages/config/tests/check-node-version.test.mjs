import { describe, expect, it } from "vitest";
import { nvmrcSatisfiesEngines } from "../../../tools/ci/check-node-version.mjs";

describe("nvmrcSatisfiesEngines", () => {
  it("accepts the repo's actual .nvmrc/engines pair", () => {
    expect(nvmrcSatisfiesEngines("v20.14.0", ">=20.14.0 <21")).toBe(true);
  });

  it("accepts a version with the exact lower bound", () => {
    expect(nvmrcSatisfiesEngines("20.14.0", ">=20.14.0 <21")).toBe(true);
  });

  it("rejects a version below the lower bound", () => {
    expect(nvmrcSatisfiesEngines("v20.13.9", ">=20.14.0 <21")).toBe(false);
  });

  it("rejects a version at/above the exclusive upper bound", () => {
    expect(nvmrcSatisfiesEngines("v21.0.0", ">=20.14.0 <21")).toBe(false);
  });

  it("rejects a malformed .nvmrc value", () => {
    expect(nvmrcSatisfiesEngines("not-a-version", ">=20.14.0 <21")).toBe(false);
  });

  it("throws on an unsupported engines clause", () => {
    expect(() => nvmrcSatisfiesEngines("v20.14.0", "~20.14.0")).toThrow(
      /unsupported engines.node clause/,
    );
  });
});
