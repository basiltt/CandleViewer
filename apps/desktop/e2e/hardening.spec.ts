import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron as electron, test, expect } from "@playwright/test";
import type { ElectronApplication } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MAIN_ENTRY = path.join(__dirname, "../dist/main/index.js");

async function launchApp(): Promise<ElectronApplication> {
  return electron.launch({ args: [MAIN_ENTRY] });
}

test.describe("Electron main-window smoke", () => {
  test("boots and the main window loads", async () => {
    const app = await launchApp();
    const window = await app.firstWindow();
    await expect(window).toBeTruthy();
    await app.close();
  });

  test("the sandboxed preload bundle exposes window.cv", async () => {
    // Regression guard: a sandboxed preload built as ESM with unresolved
    // relative imports fails silently (no thrown error, window.cv simply
    // never appears). Bundling to a single CJS file (scripts/build-preload.mjs)
    // fixes this; this assertion fails loudly if that regresses.
    const app = await launchApp();
    const window = await app.firstWindow();
    const hasCv = await window.evaluate(() => typeof (window as unknown as { cv?: unknown }).cv !== "undefined");
    expect(hasCv).toBe(true);
    await app.close();
  });
});

test.describe("Electron hardening assertion", () => {
  test("reads live webPreferences and fails if any hardening flag is off", async () => {
    const app = await launchApp();
    const window = await app.firstWindow();

    const webPreferences = await app.evaluate(({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows()[0];
      if (!win) {
        throw new Error("no BrowserWindow found");
      }
      // getLastWebPreferences is a real, documented Electron API but is not
      // present in the current @types surface; narrow via a named interface
      // rather than `any` to keep the assertion type-safe.
      interface LiveWebPreferences {
        contextIsolation?: boolean;
        nodeIntegration?: boolean;
        sandbox?: boolean;
        webSecurity?: boolean;
      }
      const webContents = win.webContents as unknown as {
        getLastWebPreferences: () => LiveWebPreferences | undefined;
      };
      const wp = webContents.getLastWebPreferences();
      return {
        contextIsolation: wp?.contextIsolation,
        nodeIntegration: wp?.nodeIntegration,
        sandbox: wp?.sandbox,
        webSecurity: wp?.webSecurity,
      };
    });

    expect(webPreferences.contextIsolation).toBe(true);
    expect(webPreferences.nodeIntegration).toBe(false);
    expect(webPreferences.sandbox).toBe(true);
    expect(webPreferences.webSecurity).toBe(true);

    await window.close();
    await app.close();
  });
});
