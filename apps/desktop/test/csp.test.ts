import { describe, expect, it } from "vitest";
import { buildCsp } from "../src/main/csp";

describe("CSP string builder", () => {
  it("matches the documented policy (snapshot)", () => {
    expect(buildCsp("http://127.0.0.1:8000")).toBe(
      "default-src 'self'; connect-src 'self' http://127.0.0.1:8000 ws://127.0.0.1:8000; img-src 'self' data:; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    );
  });

  it("includes hardening directives (object-src, base-uri, frame-ancestors, form-action)", () => {
    const csp = buildCsp();
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'none'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("form-action 'self'");
  });

  it("falls back to the default origin for a non-loopback CV_BACKEND_ORIGIN (rejects injection)", () => {
    const csp = buildCsp("http://evil.example.com\"; script-src 'unsafe-inline");
    expect(csp).not.toContain("evil.example.com");
    expect(csp).not.toContain("script-src");
    expect(csp).toContain("connect-src 'self' http://127.0.0.1:8000 ws://127.0.0.1:8000");
  });

  it("falls back to the default origin for an unparsable CV_BACKEND_ORIGIN", () => {
    const csp = buildCsp("not a url");
    expect(csp).toContain("connect-src 'self' http://127.0.0.1:8000 ws://127.0.0.1:8000");
  });

  it("accepts localhost and IPv6 loopback as valid backend origins", () => {
    expect(buildCsp("http://localhost:9000")).toContain("http://localhost:9000 ws://localhost:9000");
    expect(buildCsp("http://[::1]:9000")).toContain("http://[::1]:9000");
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
