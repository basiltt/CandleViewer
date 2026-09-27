import { describe, expect, it } from "vitest";
import { checkSequence } from "../src/runtime/index.js";
import { GENERATED_PLACEHOLDER } from "../src/generated/index.js";

describe("protocol public export surface", () => {
  it("exposes the generated placeholder marker", () => {
    expect(GENERATED_PLACEHOLDER).toBe(true);
  });

  describe("checkSequence", () => {
    it("returns ok for the next expected sequence", () => {
      expect(checkSequence(5, 6)).toBe("ok");
    });
    it("returns duplicate for a repeated sequence", () => {
      expect(checkSequence(5, 5)).toBe("duplicate");
    });
    it("returns out-of-order for a stale sequence", () => {
      expect(checkSequence(5, 3)).toBe("out-of-order");
    });
    it("returns gap for a skipped sequence", () => {
      expect(checkSequence(5, 8)).toBe("gap");
    });
  });
});
