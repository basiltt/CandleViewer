import { describe, expect, it } from "vitest";
import jsonFlat from "../../../../tools/style-dictionary/formats/json-flat.js";

describe("json/flat format", () => {
  it("flattens a nested-input dictionary to a single-level key/value map", () => {
    const dictionary = {
      allTokens: [
        { name: "color.buy.default", value: "#2EBD59" },
        { name: "space.field.gap", value: "8" },
      ],
    };
    const result = JSON.parse(jsonFlat({ dictionary }));
    expect(result).toEqual({
      "color.buy.default": "#2EBD59",
      "space.field.gap": "8",
    });
  });

  it("sorts keys for deterministic output", () => {
    const dictionary = {
      allTokens: [
        { name: "z.token", value: "1" },
        { name: "a.token", value: "2" },
      ],
    };
    const result = jsonFlat({ dictionary });
    expect(result.indexOf("a.token")).toBeLessThan(result.indexOf("z.token"));
  });

  it("recursively flattens object values (typography/shadow) with sorted nested keys", () => {
    const dictionary = {
      allTokens: [{ name: "type.ui.body", value: { fontSize: "14", fontWeight: "400" } }],
    };
    const result = JSON.parse(jsonFlat({ dictionary }));
    expect(result["type.ui.body"]).toEqual({ fontSize: "14", fontWeight: "400" });
  });

  it("produces a single-level map with no CSS/TS syntax (Electron main-process contract)", () => {
    const dictionary = { allTokens: [{ name: "color.env.live", value: "#E5484D" }] };
    const output = jsonFlat({ dictionary });
    expect(() => JSON.parse(output)).not.toThrow();
    expect(output).not.toMatch(/[:{;]\s*var\(/);
  });
});
