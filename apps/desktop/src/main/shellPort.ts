/**
 * ShellPort: abstraction boundary for shell-specific APIs (window creation,
 * IPC bridge shape). ADR-0011 (Electron vs Tauri) is `proposed`, not decided
 * (20-architecture.md); all shell-specific code stays behind this port so
 * swapping the shell implementation later does not touch app code.
 */
export interface ShellPort {
  /** Hardened webPreferences flags, asserted true at runtime by tests. */
  readonly hardening: HardeningFlags;
}

export interface HardeningFlags {
  readonly contextIsolation: boolean;
  readonly nodeIntegration: boolean;
  readonly nodeIntegrationInWorker: boolean;
  readonly nodeIntegrationInSubFrames: boolean;
  readonly sandbox: boolean;
  readonly webSecurity: boolean;
  readonly allowRunningInsecureContent: boolean;
  readonly experimentalFeatures: boolean;
}

/**
 * SR-110 (04-security-program.md §6.11): the exact, closed set of
 * webPreferences every BrowserWindow/WebContents must carry, including
 * pop-outs. `enableRemoteModule` is deliberately absent from this object and
 * from `createWindow()`'s options — the option must never be set at all
 * (the field no longer exists on supported Electron majors; re-adding it is
 * itself the regression this ticket guards against).
 */
export const HARDENED_WEB_PREFERENCES: HardeningFlags = {
  contextIsolation: true,
  nodeIntegration: false,
  nodeIntegrationInWorker: false,
  nodeIntegrationInSubFrames: false,
  sandbox: true,
  webSecurity: true,
  allowRunningInsecureContent: false,
  experimentalFeatures: false,
};
