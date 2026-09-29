import { describe, expect, it } from "vitest";
import { scanForSecrets } from "../scripts/verify.mjs";

describe("scanForSecrets", () => {
  it("returns no findings for redacted content", () => {
    const files = ["a.json"];
    const findings = scanForSecrets(files, () =>
      JSON.stringify({ symbol: "BTCUSDT", price: "50000.5" }),
    );
    expect(findings).toEqual([]);
  });

  it("flags a PEM private key block", () => {
    const files = ["key.pem"];
    const findings = scanForSecrets(files, () => "-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n");
    expect(findings).toHaveLength(1);
    expect(findings[0].pattern).toBe("PEM private key block");
  });

  it("flags a Bybit-style api_key/secret field", () => {
    const files = ["capture.json"];
    const findings = scanForSecrets(files, () => '{"api_key": "abcdef1234567890"}');
    expect(findings.length).toBeGreaterThan(0);
  });

  it("flags a bearer token", () => {
    const files = ["headers.json"];
    const findings = scanForSecrets(
      files,
      () => '{"authorization": "Bearer abcdefghijklmnopqrstuvwxyz123456"}',
    );
    expect(findings.length).toBeGreaterThan(0);
  });

  it("flags a Bybit X-BAPI-API-KEY header (E08-X03)", () => {
    const files = ["headers.json"];
    const findings = scanForSecrets(files, () => "X-BAPI-API-KEY: abcdef1234567890abcdef");
    expect(findings.length).toBeGreaterThan(0);
    expect(findings[0].pattern).toBe("Bybit X-BAPI-* auth header");
  });

  it("does not flag a redacted X-BAPI header", () => {
    const files = ["headers.json"];
    const findings = scanForSecrets(files, () => "X-BAPI-API-KEY: REDACTED");
    expect(findings).toEqual([]);
  });
});
