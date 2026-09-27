import { describe, expect, it } from "vitest";
import { evaluateLane, resolveGate } from "../../../scripts/ci_gate_resolver.mjs";

describe("evaluateLane", () => {
  /** @type {Array<["success"|"failure"|"cancelled"|"skipped", boolean, boolean, string|null]>} */
  const matrix = [
    // result, applicable, expectedOk, expectedCode
    ["success", true, true, null],
    ["success", false, true, null],
    ["failure", true, false, "CI-GATE-001"],
    ["failure", false, true, null],
    ["cancelled", true, false, "CI-GATE-001"],
    ["cancelled", false, true, null],
    ["skipped", true, false, "CI-GATE-002"],
    ["skipped", false, true, null],
  ];

  for (const [result, applicable, expectedOk, expectedCode] of matrix) {
    it(`result=${result} applicable=${applicable} -> ok=${expectedOk}`, () => {
      const outcome = evaluateLane("lane", { applicable, result });
      expect(outcome.ok).toBe(expectedOk);
      expect(outcome.code).toBe(expectedCode);
    });
  }
});

describe("resolveGate", () => {
  it("succeeds when every applicable lane succeeded and inapplicable ones skipped", () => {
    const { conclusion, failures } = resolveGate({
      js: { applicable: true, result: "success" },
      py: { applicable: false, result: "skipped" },
      engine: { applicable: false, result: "skipped" },
    });
    expect(conclusion).toBe("success");
    expect(failures).toEqual([]);
  });

  it("fails with CI-GATE-002 when an applicable lane is skipped (gate misconfiguration)", () => {
    const { conclusion, failures } = resolveGate({
      engine: { applicable: true, result: "skipped" },
    });
    expect(conclusion).toBe("failure");
    expect(failures).toHaveLength(1);
    expect(failures[0].code).toBe("CI-GATE-002");
    expect(failures[0].reason).toBe("gate misconfiguration: engine applicable but skipped");
  });

  it("fails with CI-GATE-001 when an applicable lane failed", () => {
    const { conclusion, failures } = resolveGate({
      py: { applicable: true, result: "failure" },
    });
    expect(conclusion).toBe("failure");
    expect(failures[0].code).toBe("CI-GATE-001");
  });

  it("fails with CI-GATE-001 when an applicable lane was cancelled", () => {
    const { conclusion, failures } = resolveGate({
      e2e: { applicable: true, result: "cancelled" },
    });
    expect(conclusion).toBe("failure");
    expect(failures[0].code).toBe("CI-GATE-001");
  });

  it("aggregates multiple failures across lanes", () => {
    const { conclusion, failures } = resolveGate({
      js: { applicable: true, result: "failure" },
      engine: { applicable: true, result: "skipped" },
      docs: { applicable: false, result: "skipped" },
    });
    expect(conclusion).toBe("failure");
    expect(failures).toHaveLength(2);
  });

  it("docs-only PR: all code lanes inapplicable and skipped -> success", () => {
    const { conclusion } = resolveGate({
      js: { applicable: false, result: "skipped" },
      py: { applicable: false, result: "skipped" },
      contract: { applicable: false, result: "skipped" },
      e2e: { applicable: false, result: "skipped" },
      engine: { applicable: false, result: "skipped" },
    });
    expect(conclusion).toBe("success");
  });
});
