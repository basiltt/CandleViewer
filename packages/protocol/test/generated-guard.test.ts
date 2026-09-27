import { describe, expect, it, afterEach } from "vitest";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, cpSync } from "node:fs";
import { tmpdir } from "node:os";

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = join(__dirname, "..");
const guardScript = join(packageRoot, "scripts", "check-generated-guard.mjs");

let tmpDir: string | undefined;

afterEach(() => {
  if (tmpDir) {
    rmSync(tmpDir, { recursive: true, force: true });
    tmpDir = undefined;
  }
});

describe("generated-file header guard", () => {
  it("passes on the untouched generated file", () => {
    expect(() =>
      execFileSync("node", [guardScript], { cwd: packageRoot, stdio: "pipe" }),
    ).not.toThrow();
  });

  it("fails when a generated file is hand-edited (hash mismatch)", () => {
    tmpDir = mkdtempSync(join(tmpdir(), "protocol-guard-edit-"));
    const genDir = join(tmpDir, "src", "generated");
    cpSync(join(packageRoot, "src", "generated"), genDir, { recursive: true });
    const scriptsDir = join(tmpDir, "scripts");
    mkdirSync(scriptsDir, { recursive: true });
    cpSync(guardScript, join(scriptsDir, "check-generated-guard.mjs"));

    // Hand-edit the generated file: header stays, content changes -> hash mismatch.
    const target = join(genDir, "index.ts");
    writeFileSync(
      target,
      "// GENERATED FILE — DO NOT EDIT BY HAND.\nexport const GENERATED_PLACEHOLDER = false;\n",
      "utf8",
    );

    expect(() =>
      execFileSync("node", [join(scriptsDir, "check-generated-guard.mjs")], {
        cwd: scriptsDir,
        stdio: "pipe",
      }),
    ).toThrow();
  });
});
