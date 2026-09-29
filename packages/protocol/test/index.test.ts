import { describe, expect, it } from "vitest";
import { checkSequence } from "../src/runtime/index.js";
import { generated } from "../src/index.js";

describe("protocol public export surface", () => {
  it("exposes the generated REST and WS namespaces", () => {
    expect(generated.rest).toBeDefined();
    expect(generated.ws).toBeDefined();
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
