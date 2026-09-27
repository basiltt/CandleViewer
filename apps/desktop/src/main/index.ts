import { app, BrowserWindow, session } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { HARDENED_WEB_PREFERENCES } from "./shellPort.js";
import { buildCsp } from "./csp.js";
import { logStartup, logAuditEvent } from "./logger.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// The app origin allow-list for will-navigate / window.open. In dev this is
// the Vite dev server; in a packaged build it is the local file:// origin.
const APP_ORIGIN = process.env["CV_DEV_SERVER_URL"] ?? "file://";

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
    logAuditEvent("window-open-denied", { url });
    return { action: "deny" };
  });

  win.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith(APP_ORIGIN)) {
      logAuditEvent("navigation-denied", { url });
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
