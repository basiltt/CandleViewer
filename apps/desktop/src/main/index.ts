import { app, BrowserWindow, ipcMain, session, shell } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { HARDENED_WEB_PREFERENCES } from "./shellPort.js";
import { buildCsp } from "./csp.js";
import { logStartup, logAuditEvent } from "./logger.js";
import { applyGpuFlags, probeGpu } from "./gpu.js";
import { getKekHandle } from "./keychain.js";
import { checkForUpdate } from "./updateChannel.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Single-instance lock: a second launch hands its args to the first
// instance and quits immediately rather than opening a second window (and a
// second, racing KEK-handle session).
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
} else {
  // A second launch reaches here instead of quitting; focus (and restore, if
  // minimized) the existing window rather than leaving the user with no
  // visible window and no indication the app is already running.
  app.on("second-instance", () => {
    const [existing] = BrowserWindow.getAllWindows();
    if (existing) {
      if (existing.isMinimized()) {
        existing.restore();
      }
      existing.focus();
    }
  });
}

// Packaged-build navigation is confined to the app's own dist directory; in
// dev it is confined to the Vite dev server's origin. Neither is a bare
// scheme/prefix string match (see isNavigationAllowed) so a lookalike host
// (e.g. "http://localhost:5173.evil.test") or an arbitrary local file cannot
// pass the check.
const APP_ROOT_DIR = path.resolve(__dirname, "../../../web/dist");

/**
 * Returns the origin of `url` for audit logging, or "invalid-url" if it does
 * not parse. Never returns the full URL: query strings can carry tokens
 * (C-12.6) so only the origin is safe to persist.
 */
export function safeOriginOf(url: string): string {
  try {
    return new URL(url).origin;
  } catch {
    return "invalid-url";
  }
}

/**
 * Returns true only if `url` targets the packaged app's own dist directory
 * (file: scheme, path confined to APP_ROOT_DIR) or, in dev, exactly the dev
 * server's origin. Compares parsed URL fields, never a string prefix, so
 * "file://" cannot match arbitrary local files and a dev origin cannot match
 * a lookalike host that merely starts with the same string.
 */
export function isNavigationAllowed(
  url: string,
  devServerUrl: string | undefined,
  appRootDir: string = APP_ROOT_DIR,
): boolean {
  let target: URL;
  try {
    target = new URL(url);
  } catch {
    return false;
  }

  if (devServerUrl) {
    let dev: URL;
    try {
      dev = new URL(devServerUrl);
    } catch {
      return false;
    }
    return target.origin === dev.origin;
  }

  if (target.protocol !== "file:") {
    return false;
  }
  let targetPath: string;
  try {
    targetPath = path.resolve(fileURLToPath(target));
  } catch {
    return false;
  }
  const relative = path.relative(appRootDir, targetPath);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

/**
 * Scheme `shell.openExternal` is allowed to hand off to the OS browser
 * (SR-113): only `https:` — plain `http:` is never handed to the OS shell
 * (no integrity/confidentiality on the wire, and it is not needed by any
 * genuine external destination this app links to), and no arbitrary scheme
 * (e.g. `file:`, a custom protocol, or something that could trigger a local
 * application handler unexpectedly).
 */
const ALLOWED_EXTERNAL_PROTOCOLS = new Set(["https:"]);

/**
 * Hosts `shell.openExternal` is allowed to hand off to the OS browser
 * (SR-113 requires scheme **and** host). Scheme-only checks let a
 * compromised/malicious renderer send the user's OS browser to an arbitrary
 * attacker-controlled `https:` URL (phishing, credential harvesting); this
 * closed allowlist limits external hand-off to CandleViewer's own docs host
 * and the exchange this product integrates with. Extend deliberately, in
 * review, not via runtime configuration.
 */
const ALLOWED_EXTERNAL_HOSTS = new Set(["docs.candleviewer.app", "www.bybit.com", "bybit.com"]);

/**
 * Returns true only if `url` is `https:` and its host is on the fixed
 * allowlist, and it is not the app's own dev server or packaged origin —
 * i.e. it is a genuine, known external link, not a same-origin navigation
 * that merely used `window.open`.
 */
export function isExternalLinkAllowed(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  return (
    ALLOWED_EXTERNAL_PROTOCOLS.has(parsed.protocol) && ALLOWED_EXTERNAL_HOSTS.has(parsed.hostname)
  );
}

export function createMainWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      contextIsolation: HARDENED_WEB_PREFERENCES.contextIsolation,
      nodeIntegration: HARDENED_WEB_PREFERENCES.nodeIntegration,
      nodeIntegrationInWorker: HARDENED_WEB_PREFERENCES.nodeIntegrationInWorker,
      nodeIntegrationInSubFrames: HARDENED_WEB_PREFERENCES.nodeIntegrationInSubFrames,
      sandbox: HARDENED_WEB_PREFERENCES.sandbox,
      webSecurity: HARDENED_WEB_PREFERENCES.webSecurity,
      allowRunningInsecureContent: HARDENED_WEB_PREFERENCES.allowRunningInsecureContent,
      experimentalFeatures: HARDENED_WEB_PREFERENCES.experimentalFeatures,
      // enableRemoteModule is deliberately absent (SR-110) — never set it.
    },
  });

  // "shell interactive" instrumentation (Performance notes): the window is
  // created hidden and shown only on first paint to avoid a white flash and
  // to keep the measured cold-start honest (budget #10, <=3s cold start).
  win.once("ready-to-show", () => {
    win.show();
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (isExternalLinkAllowed(url) && !isNavigationAllowed(url, process.env["CV_DEV_SERVER_URL"])) {
      logAuditEvent("external-link-opened", { url: safeOriginOf(url) });
      void shell.openExternal(url);
    } else {
      logAuditEvent("window-open-denied", { url: safeOriginOf(url) });
    }
    return { action: "deny" };
  });

  win.webContents.on("will-navigate", (event, url) => {
    if (!isNavigationAllowed(url, process.env["CV_DEV_SERVER_URL"])) {
      logAuditEvent("navigation-denied", { url: safeOriginOf(url) });
      event.preventDefault();
    }
  });

  const devServerUrl = process.env["CV_DEV_SERVER_URL"];
  if (devServerUrl) {
    void win.loadURL(devServerUrl);
  } else {
    void win.loadFile(path.join(__dirname, "../../../web/dist/index.html"));
  }

  return win;
}

function installCspHeader(): void {
  const csp = buildCsp();
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        "Content-Security-Policy": [csp],
      },
    });
  });
}

/**
 * Denies every Electron permission the app does not need. Nothing in
 * CandleViewer's scope needs camera, microphone, geolocation, MIDI or OS
 * notifications from the renderer's own request path (notifications are
 * surfaced via `ShellPort.notifications`, main-process initiated) — every
 * request is therefore explicitly denied rather than left to Electron's
 * default (which varies by permission).
 */
function installPermissionHandler(): void {
  session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => {
    callback(false);
  });
}

/** Registers the fixed set of ipcMain handlers backing the preload bridge (SR-111). */
function installIpcHandlers(): void {
  ipcMain.handle("cv:gpu:info", () => probeGpu());
  ipcMain.handle("cv:keychain:getKekHandle", () => getKekHandle());
  ipcMain.handle("cv:updates:check", () => checkForUpdate());
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

// GPU flags must be applied before app.whenReady() (Electron requirement);
// see GPU_FLAGS.md for the documented rationale of each switch.
applyGpuFlags();

void app.whenReady().then(() => {
  installCspHeader();
  installPermissionHandler();
  installIpcHandlers();
  logStartup();
  createMainWindow();
  app.emit("workspace-ready");
});
