/**
 * Auto-update channel stub (SR-115). Absorbed from the withdrawn E10-T03
 * per the scope-reconciliation note in this ticket: `capabilities.autoUpdate`
 * stays `false` and no download/install path exists until code signing lands
 * (R5/E48). This module exposes only a version read and a disabled check —
 * there is no code path anywhere in this file that can install code.
 */
import { app } from "electron";

export const UPDATE_CHANNEL_DISABLED_REASON = "UPDATE_CHANNEL_DISABLED";

export interface UpdateCheckResult {
  readonly state: "up-to-date" | "error";
  readonly reason?: string;
}

/** Always `false` pre-signing (SR-115) — never derived from config or a flag. */
export function isAutoUpdateEnabled(): boolean {
  return false;
}

export function getCurrentVersion(): string {
  return app.getVersion();
}

/**
 * Reports the disabled state rather than performing a real update check.
 * Never contacts a remote host: with signing absent there is nothing to
 * verify a downloaded artefact against, so no artefact is ever fetched.
 */
export function checkForUpdate(): UpdateCheckResult {
  return { state: "error", reason: UPDATE_CHANNEL_DISABLED_REASON };
}

/**
 * Always refuses. Exists so a caller cannot reach an "apply"/"install" path
 * by construction — there is no install implementation to call into.
 */
export function applyUpdate(): never {
  throw new Error(UPDATE_CHANNEL_DISABLED_REASON);
}
