import { describe, expect, it, vi } from "vitest";
import { pathToFileURL } from "node:url";
import path from "node:path";

// src/main/index.ts calls app.on(...) / app.whenReady() at module scope, so
// the real "electron" module (unavailable under vitest's node environment)
// must be mocked before the module under test is imported.
vi.mock("electron", () => ({
  app: {
    on: vi.fn(),
    whenReady: vi.fn().mockResolvedValue(undefined),
    getVersion: vi.fn().mockReturnValue("0.0.0"),
    getPath: vi.fn().mockReturnValue("/tmp"),
    emit: vi.fn(),
  },
  BrowserWindow: vi.fn().mockImplementation(() => ({
    webContents: {
      setWindowOpenHandler: vi.fn(),
      on: vi.fn(),
    },
    loadURL: vi.fn(),
    loadFile: vi.fn(),
  })),
  session: { defaultSession: { webRequest: { onHeadersReceived: vi.fn() } } },
}));

const { isNavigationAllowed, safeOriginOf } = await import("../src/main/index");

const APP_ROOT = path.resolve(process.platform === "win32" ? "C:\\app\\web\\dist" : "/app/web/dist");

describe("isNavigationAllowed", () => {
  it("allows navigation to a file inside the packaged app root", () => {
    const url = pathToFileURL(path.join(APP_ROOT, "index.html")).href;
    expect(isNavigationAllowed(url, undefined, APP_ROOT)).toBe(true);
  });

  it("denies navigation to an arbitrary local file (file:// prefix bypass)", () => {
    const outside = pathToFileURL(path.resolve(APP_ROOT, "..", "..", "secrets.txt")).href;
    expect(isNavigationAllowed(outside, undefined, APP_ROOT)).toBe(false);
  });

  it("denies non-file navigation when there is no dev server", () => {
    expect(isNavigationAllowed("https://example.com", undefined, APP_ROOT)).toBe(false);
  });

  it("allows navigation to exactly the dev server origin", () => {
    expect(isNavigationAllowed("http://localhost:5173/", "http://localhost:5173")).toBe(true);
    expect(isNavigationAllowed("http://localhost:5173/route", "http://localhost:5173")).toBe(true);
  });

  it("denies a lookalike host that merely starts with the dev origin string", () => {
    expect(
      isNavigationAllowed("http://localhost:5173.evil.test/", "http://localhost:5173"),
    ).toBe(false);
  });

  it("denies a different scheme or port than the dev server", () => {
    expect(isNavigationAllowed("https://localhost:5173/", "http://localhost:5173")).toBe(false);
    expect(isNavigationAllowed("http://localhost:9999/", "http://localhost:5173")).toBe(false);
  });

  it("denies an unparseable URL", () => {
    expect(isNavigationAllowed("not a url", undefined, APP_ROOT)).toBe(false);
  });
});

describe("safeOriginOf", () => {
  it("returns only the origin, dropping any query string / token", () => {
    expect(safeOriginOf("https://example.com/path?token=secret")).toBe("https://example.com");
  });

  it("returns a fixed placeholder for an unparseable URL instead of throwing", () => {
    expect(safeOriginOf("not a url")).toBe("invalid-url");
  });
});
