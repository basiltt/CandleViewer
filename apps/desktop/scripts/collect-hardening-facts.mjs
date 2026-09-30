// E10-X02: collects the runtime facts the electron-hardening gate asserts (SR-110, SR-112).
//
// Launches the PACKAGED build (apps/desktop/dist) headlessly via Playwright-Electron and reads
// `webContents.getLastWebPreferences()` for EVERY window that exists (a pop-out created with
// weaker options is the realistic regression), plus the CSP header string the main process
// builds (`dist/main/csp.js#buildCsp`, the exact function installCspHeader() uses).
//
import console from "node:console";
// Usage: node scripts/collect-hardening-facts.mjs <out.json>
import { writeFileSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { _electron as electron } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const dist = path.join(here, "../dist");
const out = process.argv[2];
if (!out) {
  console.error("usage: collect-hardening-facts.mjs <out.json>");
  process.exit(2);
}

const { buildCsp } = await import(pathToFileURL(path.join(dist, "main/csp.js")).href);

const app = await electron.launch({
  args: [path.join(dist, "main/index.js")],
});
try {
  await app.firstWindow();
  const windows = await app.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows().map((w, i) => ({
      name: `window-${i}`,
      title: w.getTitle(),
      webPreferences: w.webContents.getLastWebPreferences(),
    })),
  );
  writeFileSync(
    out,
    JSON.stringify(
      {
        cspHeader: buildCsp(),
        // Flip to true once the env badge (E10 env-badge ticket) puts DEMO/LIVE in the title.
        requireEnvTitle: false,
        windows,
      },
      null,
      2,
    ),
    "utf-8",
  );
  console.log(`collected ${windows.length} window(s) -> ${out}`);
} finally {
  await app.close();
}
