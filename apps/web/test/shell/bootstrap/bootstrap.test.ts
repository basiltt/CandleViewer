import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  BOOTSTRAP_TIMEOUT_MS,
  SLOW_BOOT_THRESHOLD_MS,
  runBootstrap,
} from "../../../src/shell/bootstrap/bootstrap.js";
import { getShellState, resetShellState } from "../../../src/shell/bootstrap/store.js";
import { getMeClaims, resetMeClaims } from "../../../src/lib/auth/meCache.js";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const ME_BODY = {
  user: { id: "u1", username: "owner", email: "o@example.com", roles: ["owner"], status: "active" },
  role: "owner",
  permissions: ["rules:author"],
  accounts: [],
  session: { session_id: "s1", environment: "demo", elevated_until: null },
};

describe("runBootstrap", () => {
  beforeEach(() => {
    resetShellState();
    resetMeClaims();
  });

  it("issues exactly one request each to /me, /me/preferences and /me/keymap, in parallel", async () => {
    const calls: string[] = [];
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      calls.push(path);
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse(ME_BODY));
      if (path === "/api/v1/me/preferences")
        return Promise.resolve(jsonResponse({ appearance: { theme: "dark" } }));
      return Promise.resolve(jsonResponse({ bindings: [] }));
    });
    await runBootstrap({ fetchImpl });
    expect(calls.sort()).toEqual(["/api/v1/me", "/api/v1/me/keymap", "/api/v1/me/preferences"]);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it("sets the environment from /me and never assumes a default before it resolves", async () => {
    expect(getShellState().environment).toBe("unknown");
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse(ME_BODY));
      return Promise.resolve(jsonResponse({}));
    });
    await runBootstrap({ fetchImpl });
    expect(getShellState().environment).toBe("demo");
  });

  it("populates the me-claims cache route guards read", async () => {
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse(ME_BODY));
      return Promise.resolve(jsonResponse({}));
    });
    await runBootstrap({ fetchImpl });
    expect(getMeClaims()).toMatchObject({ authenticated: true, role: "owner" });
  });

  it("sets bootstrap to failed with http_error reason on a /me 500", async () => {
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse({}, 500));
      return Promise.resolve(jsonResponse({}));
    });
    await runBootstrap({ fetchImpl });
    expect(getShellState().bootstrap).toEqual({
      kind: "failed",
      reason: "http_error",
      status: 500,
    });
    expect(getShellState().environment).toBe("unknown");
  });

  it("proceeds with defaults and a warning when preferences fails, without failing the whole boot", async () => {
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse(ME_BODY));
      if (path === "/api/v1/me/preferences") return Promise.resolve(jsonResponse({}, 500));
      return Promise.resolve(jsonResponse({ bindings: [] }));
    });
    await runBootstrap({ fetchImpl });
    expect(getShellState().bootstrap).toEqual({ kind: "ready" });
    expect(getShellState().preferencesWarning).toBeTruthy();
  });

  it("proceeds with a warning when keymap fails — a broken keymap must not block login", async () => {
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      if (path === "/api/v1/me") return Promise.resolve(jsonResponse(ME_BODY));
      if (path === "/api/v1/me/keymap") return Promise.resolve(jsonResponse({}, 500));
      return Promise.resolve(jsonResponse({ appearance: {} }));
    });
    await runBootstrap({ fetchImpl });
    expect(getShellState().bootstrap).toEqual({ kind: "ready" });
    expect(getShellState().keymapWarning).toBeTruthy();
  });

  it("marks bootstrap as slow after SLOW_BOOT_THRESHOLD_MS while /me is still pending", async () => {
    vi.useFakeTimers();
    let resolveMe!: (value: Response) => void;
    const fetchImpl = vi.fn().mockImplementation((path: string) => {
      if (path === "/api/v1/me") {
        return new Promise<Response>((resolve) => {
          resolveMe = resolve;
        });
      }
      return Promise.resolve(jsonResponse({}));
    });
    const pending = runBootstrap({ fetchImpl });
    await vi.advanceTimersByTimeAsync(SLOW_BOOT_THRESHOLD_MS);
    expect(getShellState().bootstrap).toEqual({ kind: "slow" });
    resolveMe(jsonResponse(ME_BODY));
    await vi.runAllTimersAsync();
    await pending;
    vi.useRealTimers();
  });

  it("exposes the bootstrap timeout constant used for each call", () => {
    expect(BOOTSTRAP_TIMEOUT_MS).toBeGreaterThan(0);
  });
});
