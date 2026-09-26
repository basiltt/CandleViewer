import { describe, expect, it } from "vitest";
import { noRestrictedImportsRuleSet } from "../no-restricted-imports.mjs";
import { prettierConfig } from "../prettier.config.mjs";
import { vitestPreset } from "../vitest.preset.mjs";

describe("no-restricted-imports rule set stub", () => {
  it("exports a paths array with at least one entry", () => {
    expect(Array.isArray(noRestrictedImportsRuleSet.paths)).toBe(true);
    expect(noRestrictedImportsRuleSet.paths.length).toBeGreaterThan(0);
  });

  it("exports a patterns array with at least one entry", () => {
    expect(Array.isArray(noRestrictedImportsRuleSet.patterns)).toBe(true);
    expect(noRestrictedImportsRuleSet.patterns.length).toBeGreaterThan(0);
  });
});

describe("prettier config", () => {
  it("pins line width and quote style deterministically", () => {
    expect(prettierConfig.printWidth).toBe(100);
    expect(prettierConfig.singleQuote).toBe(false);
  });
});

describe("vitest preset", () => {
  it("sets coverage thresholds meeting the frontend floor (C-9.4)", () => {
    expect(vitestPreset.test.coverage.thresholds.lines).toBeGreaterThanOrEqual(80);
    expect(vitestPreset.test.coverage.thresholds.branches).toBeGreaterThanOrEqual(70);
  });
});
