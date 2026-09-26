import { describe, expect, it } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { listFiles, verifyDirectories } from "../scripts/verify.mjs";

describe("listFiles", () => {
  it("returns [] for a directory that does not exist", () => {
    expect(listFiles(join(tmpdir(), "does-not-exist-xyz"))).toEqual([]);
  });

  it("returns [] when given a file path instead of a directory", () => {
    const sandbox = mkdtempSync(join(tmpdir(), "fixtures-listfiles-"));
    const file = join(sandbox, "not-a-dir.txt");
    writeFileSync(file, "x");
    try {
      expect(listFiles(file)).toEqual([]);
    } finally {
      rmSync(sandbox, { recursive: true, force: true });
    }
  });

  it("recurses into subdirectories and skips .gitkeep", () => {
    const sandbox = mkdtempSync(join(tmpdir(), "fixtures-listfiles-"));
    mkdirSync(join(sandbox, "nested"), { recursive: true });
    writeFileSync(join(sandbox, ".gitkeep"), "");
    writeFileSync(join(sandbox, "nested", "a.json"), "{}");
    try {
      const files = listFiles(sandbox);
      expect(files).toHaveLength(1);
      expect(files[0]).toContain("a.json");
    } finally {
      rmSync(sandbox, { recursive: true, force: true });
    }
  });
});

describe("verifyDirectories", () => {
  it("finds no issues in a clean directory tree", () => {
    const sandbox = mkdtempSync(join(tmpdir(), "fixtures-verifydirs-"));
    mkdirSync(join(sandbox, "raw"), { recursive: true });
    writeFileSync(join(sandbox, "raw", "clean.json"), '{"symbol": "BTCUSDT"}');
    try {
      const { files, findings } = verifyDirectories([join(sandbox, "raw")]);
      expect(files).toHaveLength(1);
      expect(findings).toEqual([]);
    } finally {
      rmSync(sandbox, { recursive: true, force: true });
    }
  });

  it("reports findings for a secret-shaped fixture", () => {
    const sandbox = mkdtempSync(join(tmpdir(), "fixtures-verifydirs-"));
    mkdirSync(join(sandbox, "raw"), { recursive: true });
    writeFileSync(join(sandbox, "raw", "leak.json"), '{"api_key": "sk-abcdef1234567890"}');
    try {
      const { findings } = verifyDirectories([join(sandbox, "raw")]);
      expect(findings.length).toBeGreaterThan(0);
    } finally {
      rmSync(sandbox, { recursive: true, force: true });
    }
  });
});

describe("verify.mjs CLI (end-to-end)", () => {
  it("exits 0 when raw/ and golden/ are clean", async () => {
    const { execFileSync } = await import("node:child_process");
    const { fileURLToPath } = await import("node:url");
    const { dirname } = await import("node:path");
    const __dirname = dirname(fileURLToPath(import.meta.url));
    const packageRoot = join(__dirname, "..");
    const verifyScript = join(packageRoot, "scripts", "verify.mjs");
    expect(() =>
      execFileSync("node", [verifyScript], { cwd: packageRoot, stdio: "pipe" }),
    ).not.toThrow();
  });
});
