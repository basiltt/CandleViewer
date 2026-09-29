import { describe, expect, it } from "vitest";
import {
  evaluateAccess,
  isStepUpFresh,
  STEP_UP_TTL_MS,
  type MeClaims,
} from "../../src/routes/rbac";

const base: MeClaims = {
  authenticated: true,
  role: "viewer",
  permissions: [],
  elevatedAt: null,
};

describe("evaluateAccess", () => {
  it("allows a public route with no session", () => {
    const unauth: MeClaims = {
      authenticated: false,
      role: null,
      permissions: [],
      elevatedAt: null,
    };
    expect(evaluateAccess({ roles: "public" }, unauth)).toEqual({ kind: "allow" });
  });

  it("redirects to login when unauthenticated on a protected route", () => {
    const unauth: MeClaims = {
      authenticated: false,
      role: null,
      permissions: [],
      elevatedAt: null,
    };
    expect(evaluateAccess({ roles: ["owner"] }, unauth)).toEqual({ kind: "redirect-login" });
  });

  it("allows a role explicitly listed", () => {
    expect(evaluateAccess({ roles: ["owner", "viewer"] }, base)).toEqual({ kind: "allow" });
  });

  it("denies with 403 by default", () => {
    expect(evaluateAccess({ roles: ["owner"] }, base)).toEqual({ kind: "deny", as: "403" });
  });

  it("denies /admin/** with 404 per the sitemap note, not 403", () => {
    expect(evaluateAccess({ roles: ["owner"], denyAs: "404" }, base)).toEqual({
      kind: "deny",
      as: "404",
    });
  });

  it("requires step-up when the route demands it and none is recorded", () => {
    const owner: MeClaims = { ...base, role: "owner" };
    expect(evaluateAccess({ roles: ["owner"], requiresStepUp: true }, owner)).toEqual({
      kind: "step-up-required",
    });
  });

  it("allows when step-up is fresh", () => {
    const owner: MeClaims = { ...base, role: "owner", elevatedAt: new Date().toISOString() };
    expect(evaluateAccess({ roles: ["owner"], requiresStepUp: true }, owner)).toEqual({
      kind: "allow",
    });
  });
});

describe("isStepUpFresh", () => {
  it("is false when never elevated", () => {
    expect(isStepUpFresh(base)).toBe(false);
  });

  it("is true just under the 30-minute TTL", () => {
    const elevatedAt = new Date(Date.now() - (STEP_UP_TTL_MS - 1000)).toISOString();
    expect(isStepUpFresh({ ...base, elevatedAt })).toBe(true);
  });

  it("is false once the 30-minute TTL has elapsed", () => {
    const elevatedAt = new Date(Date.now() - (STEP_UP_TTL_MS + 1000)).toISOString();
    expect(isStepUpFresh({ ...base, elevatedAt })).toBe(false);
  });

  it("is false for an unparsable timestamp", () => {
    expect(isStepUpFresh({ ...base, elevatedAt: "not-a-date" })).toBe(false);
  });
});
