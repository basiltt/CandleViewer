import { describe, expect, it } from "vitest";
import { buildCsp } from "../src/main/csp";

describe("CSP string builder", () => {
  it("matches the documented policy (snapshot)", () => {
    expect(buildCsp("http://127.0.0.1:8000")).toBe(
      "default-src 'self'; connect-src 'self' http://127.0.0.1:8000 ws://127.0.0.1:8000; img-src 'self' data:; style-src 'self' 'unsafe-inline'",
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

  it("does not allow an unrestricted connect-src", () => {
    const csp = buildCsp();
    expect(csp).not.toContain("connect-src 'self' ws: wss:");
    expect(csp).toMatch(/connect-src 'self' https?:\/\/\S+ wss?:\/\/\S+/);
  });
});
