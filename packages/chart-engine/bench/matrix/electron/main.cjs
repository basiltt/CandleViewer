// E06-T01 Electron harness shell (CommonJS: sandboxed preloads and a plain `electron`
// launch cannot be ESM). Carries the E06-X01 / 04-security-program hardening baseline
// so the numbers are taken against a shell we could actually ship:
//   contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity on,
//   strict CSP (set on the page + enforced again here via response headers),
//   allow-list preload, navigation and window.open BLOCKED, permissions denied.
// It loads ONE loopback URL (the runner's harness server) and nothing else.
"use strict";
const { app, BrowserWindow, session } = require("electron");
const path = require("node:path");
const { ELECTRON_FLAGSETS } = require("./flagsets.cjs");

const target = process.env.CV_MATRIX_URL;
const flagsetName = process.env.CV_MATRIX_FLAGSET || "default";
const flagset = ELECTRON_FLAGSETS[flagsetName];
if (!target || !flagset) {
  console.error(
    `[electron-matrix] need CV_MATRIX_URL and a known CV_MATRIX_FLAGSET (${flagsetName})`,
  );
  process.exit(2);
}
const origin = new URL(target).origin;

// Switches must be set before app is ready.
for (const [name, value] of flagset.switches) {
  if (value === undefined) app.commandLine.appendSwitch(name);
  else app.commandLine.appendSwitch(name, value);
}

const CSP =
  "default-src 'none'; script-src 'self'; worker-src 'self'; connect-src 'self'; " +
  "style-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'";

app.whenReady().then(() => {
  session.defaultSession.setPermissionRequestHandler((_wc, _perm, cb) => cb(false));
  session.defaultSession.webRequest.onHeadersReceived((details, cb) => {
    cb({ responseHeaders: { ...details.responseHeaders, "Content-Security-Policy": [CSP] } });
  });

  const win = new BrowserWindow({
    width: 1700,
    height: 1000,
    show: true, // a hidden window can be occlusion-throttled and would not be representative
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      nodeIntegrationInWorker: false,
      nodeIntegrationInSubFrames: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      experimentalFeatures: false,
    },
  });
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.webContents.on("will-navigate", (e, url) => {
    if (new URL(url).origin !== origin) e.preventDefault();
  });

  const v = process.versions;
  const u = new URL(target);
  u.searchParams.set("sv_electron", v.electron);
  u.searchParams.set("sv_chromium", v.chrome);
  win.loadURL(u.toString());

  // Resident memory per process (ADR-0011 "100-150 MB higher than Tauri" evidence).
  const sample = async () => {
    try {
      const mb = app.getAppMetrics().reduce((a, m) => a + (m.memory.workingSetSize || 0), 0) / 1024;
      const gpu = await app.getGPUInfo("basic").catch(() => null);
      await fetch(`${origin}/shell-metrics`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          workingSetMb: Math.round(mb),
          processes: app.getAppMetrics().length,
          gpuDevice: gpu && gpu.gpuDevice ? gpu.gpuDevice : null,
        }),
      });
    } catch {
      /* metrics are best-effort; the runner also samples the OS */
    }
  };
  setInterval(sample, 15_000);
  setTimeout(sample, 5_000);
});

app.on("window-all-closed", () => app.quit());
