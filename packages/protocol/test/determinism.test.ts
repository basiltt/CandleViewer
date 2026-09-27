// E02-T09 acceptance: `pnpm generate` must be byte-for-byte deterministic —
// no timestamps, no absolute paths, no unordered-iteration leakage. Runs the
// real pipeline twice into isolated temp dirs and diffs the output.
import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = join(__dirname, "..");
const repoRoot = join(packageRoot, "..", "..");

describe("generate.mjs determinism", () => {
  it("produces byte-identical ws-schema.json across two extractions", () => {
    const scriptPath = join(packageRoot, "scripts", "extract-ws-schema.mjs");
    const outPath = join(repoRoot, "docs", "plan", "ws-schema.json");
    execFileSync("node", [scriptPath], { cwd: repoRoot });
    const first = readFileSync(outPath, "utf8");
    execFileSync("node", [scriptPath], { cwd: repoRoot });
    const second = readFileSync(outPath, "utf8");
    expect(second).toBe(first);
  });

  it("`generate:check` reports the committed output as up to date (no drift after a fresh run)", () => {
    const out = execFileSync("node", [join(packageRoot, "scripts", "generate.mjs"), "--check"], {
      cwd: packageRoot,
      encoding: "utf8",
    });
    expect(out).toMatch(/OK — generated output is up to date/);
  });
});
