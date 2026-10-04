/* global process, console */
// Gate 2 collector (E47-T02): Lighthouse accessibility score per screen ->
// reports/a11y/lighthouse.json ({"<screen>": 0..1 | null}). null = runner
// failure for that screen, which gates.py reports as A11Y-INFRA (never a score
// failure). Lighthouse is fetched pinned via npx so no manifest/lockfile change.
// Usage: node lighthouse.collect.mjs   (expects `vite preview` on :4173)
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "@playwright/test";

const LH = "lighthouse@12.2.1";
const BASE = process.env.A11Y_BASE_URL ?? "http://127.0.0.1:4173";
const OUT = process.env.A11Y_REPORT_DIR ?? "../../reports/a11y";
const PATHS = (process.env.A11Y_LH_SCREENS ?? "R-001:/login,R-901:/404").split(",");

const scores = {};
const tmp = mkdtempSync(join(tmpdir(), "lh-"));
for (const entry of PATHS) {
  const [id, path] = entry.split(":");
  const file = join(tmp, `${id}.json`);
  try {
    execFileSync(
      "npx",
      [
        "--yes",
        LH,
        `${BASE}${path}`,
        "--only-categories=accessibility",
        "--output=json",
        `--output-path=${file}`,
        "--chrome-flags=--headless=new --no-sandbox",
        "--quiet",
      ],
      {
        env: { ...process.env, CHROME_PATH: process.env.CHROME_PATH ?? chromium.executablePath() },
        stdio: "inherit",
        shell: process.platform === "win32",
        timeout: 120_000,
      },
    );
    scores[id] = JSON.parse(readFileSync(file, "utf8")).categories.accessibility.score ?? null;
  } catch (err) {
    console.error(`lighthouse failed for ${id}: ${err.message}`);
    scores[id] = null;
  }
}
mkdirSync(OUT, { recursive: true });
writeFileSync(join(OUT, "lighthouse.json"), JSON.stringify(scores, null, 2));
