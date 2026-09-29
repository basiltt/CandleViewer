import { describe, expect, it } from "vitest";
import typescriptNestedObject from "../../../../tools/style-dictionary/formats/typescript-nested.js";

describe("typescript/nested-object format", () => {
  it("nests dot-path token names into a typed object literal", () => {
    const dictionary = {
      allTokens: [
        { name: "color.buy.default", value: "#2EBD59" },
        { name: "color.sell.default", value: "#E5484D" },
        { name: "space.field.gap", value: "8" },
      ],
    };
    const output = typescriptNestedObject({ dictionary });
    expect(output).toContain("export const tokens = {");
    expect(output).toContain("export type Tokens = typeof tokens;");
    expect(output).toMatch(/color:\s*{\s*[\s\S]*buy:\s*{\s*[\s\S]*default: "#2EBD59"/);
    expect(output).toContain('gap: "8"');
  });

  it("quotes property keys that are not valid identifiers", () => {
    const dictionary = { allTokens: [{ name: "color.buy-hc.default", value: "#6BD48A" }] };
    const output = typescriptNestedObject({ dictionary });
    expect(output).toContain('"buy-hc"');
  });

  it("is deterministic across repeated calls (sorted keys)", () => {
    const dictionary = {
      allTokens: [
        { name: "z.token", value: "1" },
        { name: "a.token", value: "2" },
      ],
    };
    const first = typescriptNestedObject({ dictionary });
    const second = typescriptNestedObject({ dictionary });
    expect(first).toBe(second);
    expect(first.indexOf("a:")).toBeLessThan(first.indexOf("z:"));
  });
});
