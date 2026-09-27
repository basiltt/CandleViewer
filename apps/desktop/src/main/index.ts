import { app, BrowserWindow, session } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { HARDENED_WEB_PREFERENCES } from "./shellPort.js";
import { buildCsp } from "./csp.js";
import { logStartup, logAuditEvent } from "./logger.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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

export function createMainWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      contextIsolation: HARDENED_WEB_PREFERENCES.contextIsolation,
      nodeIntegration: HARDENED_WEB_PREFERENCES.nodeIntegration,
      sandbox: HARDENED_WEB_PREFERENCES.sandbox,
      webSecurity: HARDENED_WEB_PREFERENCES.webSecurity,
    },
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    logAuditEvent("window-open-denied", { url: safeOriginOf(url) });
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

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

void app.whenReady().then(() => {
  installCspHeader();
  logStartup();
  createMainWindow();
  app.emit("workspace-ready");
});
