import { describe, expect, it } from "vitest";
import { TOKEN_SCHEMA_VERSION, Placeholder } from "../src/index.js";

describe("@candleviewer/ui public export surface", () => {
  it("exposes the token schema version", () => {
    expect(TOKEN_SCHEMA_VERSION).toBe(1);
  });

  it("exposes the Placeholder component as a function", () => {
    expect(typeof Placeholder).toBe("function");
  });
});
