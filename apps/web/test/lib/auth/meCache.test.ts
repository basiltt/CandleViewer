import { describe, expect, it, beforeEach } from "vitest";
import {
  getMeClaims,
  setMeClaims,
  recordStepUp,
  resetMeClaims,
} from "../../../src/lib/auth/meCache";

describe("meCache", () => {
  beforeEach(() => {
    resetMeClaims();
  });

  it("defaults to an unauthenticated claims object", () => {
    expect(getMeClaims()).toEqual({
      authenticated: false,
      role: null,
      permissions: [],
      elevatedAt: null,
    });
  });

  it("returns whatever was last set, synchronously", () => {
    setMeClaims({
      authenticated: true,
      role: "owner",
      permissions: ["rules:author"],
      elevatedAt: null,
    });
    expect(getMeClaims().role).toBe("owner");
  });

  it("records a step-up timestamp without touching other fields", () => {
    setMeClaims({ authenticated: true, role: "owner", permissions: [], elevatedAt: null });
    recordStepUp("2026-09-29T12:00:00Z");
    const claims = getMeClaims();
    expect(claims.elevatedAt).toBe("2026-09-29T12:00:00Z");
    expect(claims.role).toBe("owner");
  });
});
