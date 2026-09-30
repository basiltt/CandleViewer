// Fixtures for cv-electron-unsafe-webprefs (run: python tools/ci/check_semgrep_rule_tests.py).
declare class BrowserWindow {
  constructor(opts: unknown);
}

export function createMainWindow(): BrowserWindow {
  return new BrowserWindow({ webPreferences: { sandbox: true, contextIsolation: true } }); // ok: cv-electron-unsafe-webprefs
}

export function popOutBypassingFactory(): BrowserWindow {
  return new BrowserWindow({ width: 10 }); // ruleid: cv-electron-unsafe-webprefs
}

export const weakSandbox = { sandbox: false }; // ruleid: cv-electron-unsafe-webprefs
export const weakIsolation = { contextIsolation: false }; // ruleid: cv-electron-unsafe-webprefs
export const nodeOn = { nodeIntegration: true }; // ruleid: cv-electron-unsafe-webprefs
export const weakWebSecurity = { webSecurity: false }; // ruleid: cv-electron-unsafe-webprefs
export const remote = { enableRemoteModule: true }; // ruleid: cv-electron-unsafe-webprefs
export const hardened = { sandbox: true, nodeIntegration: false }; // ok: cv-electron-unsafe-webprefs
