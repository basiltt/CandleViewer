import { describe, expect, it } from "vitest";
import { getKekHandle } from "../src/main/keychain";

describe("getKekHandle (SR-119)", () => {
  it("returns an opaque handle string, not key material", () => {
    const handle = getKekHandle();
    expect(typeof handle).toBe("string");
    expect(handle).toMatch(/^kek-handle-/);
  });

  it("returns the same handle across calls within a session", () => {
    expect(getKekHandle()).toBe(getKekHandle());
  });

  it("never contains anything resembling key material (base64/hex key bytes)", () => {
    const handle = getKekHandle();
    // The handle is a fixed prefix plus a UUID; a real key would never be
    // this short, this structured, or match this exact shape.
    expect(handle).toMatch(
      /^kek-handle-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );
  });
});
