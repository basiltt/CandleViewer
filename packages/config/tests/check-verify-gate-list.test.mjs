import { describe, expect, it } from "vitest";
import {
  parseConstitutionChecks,
  parseVerifyGateCalls,
  diffGateLists,
} from "../../../scripts/check-verify-gate-list.mjs";

const SAMPLE_TABLE = `## 9. Quality gates

| # | Check name | Gate |
|---|---|---|
| 1 | \`lint\` | ESLint |
| 2 | \`typecheck\` | tsc |
| 3 | \`unit-backend\` | pytest |

---
`;

const MATCHING_SCRIPT = `
gate(1, "lint", () => run("pnpm", ["lint"]));
gate(2, "typecheck", () => run("pnpm", ["typecheck"]));
gate(3, "unit-backend", () => run("uv", ["run", "pytest"]));
gate("guard", "threshold-guard (C-9.4)", () => run("python", ["tools/ci/quality_gates.py"]));
`;

describe("parseConstitutionChecks", () => {
  it("extracts numbered check names in order", () => {
    expect(parseConstitutionChecks(SAMPLE_TABLE)).toEqual([
      { n: 1, name: "lint" },
      { n: 2, name: "typecheck" },
      { n: 3, name: "unit-backend" },
    ]);
  });

  it("throws when the §9 table header is missing", () => {
    expect(() => parseConstitutionChecks("no table here")).toThrow(/Check name/);
  });
});

describe("parseVerifyGateCalls", () => {
  it("extracts numbered gate() calls and ignores the non-numbered guard call", () => {
    expect(parseVerifyGateCalls(MATCHING_SCRIPT)).toEqual([
      { n: 1, name: "lint" },
      { n: 2, name: "typecheck" },
      { n: 3, name: "unit-backend" },
    ]);
  });
});

describe("diffGateLists", () => {
  const expected = [
    { n: 1, name: "lint" },
    { n: 2, name: "typecheck" },
    { n: 3, name: "unit-backend" },
  ];

  it("reports no diff when the lists match", () => {
    expect(diffGateLists(expected, expected)).toEqual({ missing: [], mismatched: [] });
  });

  it("reports a missing gate", () => {
    const actual = [expected[0], expected[1]];
    const { missing } = diffGateLists(expected, actual);
    expect(missing).toEqual(["#3 unit-backend"]);
  });

  it("reports a mismatched name at the same number", () => {
    const actual = [expected[0], expected[1], { n: 3, name: "wrong-name" }];
    const { mismatched } = diffGateLists(expected, actual);
    expect(mismatched).toEqual(['#3: expected "unit-backend", got "wrong-name"']);
  });
});
