export type {
  CrashEntry,
  DeepLinkPayload,
  GpuInfo,
  ShellCapabilities,
  ShellPort,
  TrayStatus,
  UpdateStatus,
  WindowBounds,
  WindowState,
} from "./ShellPort.js";
export { BROWSER_CAPABILITIES, createBrowserShellAdapter } from "./BrowserShellAdapter.js";
export {
  ELECTRON_CAPABILITIES,
  createElectronShellAdapter,
  type CvBridge,
} from "./ElectronShellAdapter.js";

import type { ShellPort } from "./ShellPort.js";
import { createBrowserShellAdapter } from "./BrowserShellAdapter.js";
import { createElectronShellAdapter } from "./ElectronShellAdapter.js";

/**
 * Picks the adapter matching the current host: `window.cv` present means the
 * Electron preload script ran, so use the preload-backed adapter; otherwise
 * fall back to the honest-degradation browser adapter. Never sniffs the user
 * agent — the presence of the typed bridge is the only signal.
 */
export function createShellPort(): ShellPort {
  return typeof window !== "undefined" && window.cv
    ? createElectronShellAdapter()
    : createBrowserShellAdapter();
}
