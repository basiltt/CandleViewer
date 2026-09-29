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
  readonly sandbox: boolean;
  readonly webSecurity: boolean;
}

export const HARDENED_WEB_PREFERENCES: HardeningFlags = {
  contextIsolation: true,
  nodeIntegration: false,
  sandbox: true,
  webSecurity: true,
};
