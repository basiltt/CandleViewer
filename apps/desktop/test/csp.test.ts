import { describe, expect, it } from "vitest";
import { buildCsp } from "../src/main/csp";

describe("CSP string builder", () => {
  it("matches the documented policy (snapshot)", () => {
    expect(buildCsp()).toBe(
      "default-src 'self'; connect-src 'self' ws: wss:; img-src 'self' data:; style-src 'self' 'unsafe-inline'",
    );
  });

  it("scopes 'unsafe-inline' to style-src only", () => {
    const csp = buildCsp();
    const directives = csp.split("; ");
    for (const directive of directives) {
      if (directive.includes("unsafe-inline")) {
        expect(directive.startsWith("style-src")).toBe(true);
      }
    }
  });
});
