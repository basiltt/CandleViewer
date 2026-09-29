// Machine descriptor capture (E06-K01 ticket "The machine is always
// identified" AC): CPU, GPU, driver version, OS build, and (Tauri) WebView2
// version. A run missing any required field fails rather than reporting
// anonymous numbers.
import { cpus, totalmem, platform, release, arch } from "node:os";

/**
 * @typedef {{
 *   cpu: string,
 *   cpuCount: number,
 *   totalMemMb: number,
 *   os: string,
 *   osBuild: string,
 *   arch: string,
 *   gpu: string,
 *   driver: string,
 *   webview2Version: string | null,
 * }} MachineDescriptor
 */

/** Fields every report is required to carry (ticket AC: "missing any of these fields fails"). */
export const REQUIRED_DESCRIPTOR_FIELDS = /** @type {const} */ ([
  "cpu",
  "os",
  "osBuild",
  "gpu",
  "driver",
]);

/**
 * Captures the machine descriptor. `gpu`/`driver` cannot be read from Node
 * directly (no GPU API on the host process) so headless-Chromium/Electron
 * callers must pass them in via `overrides` (read from
 * `chrome://gpu`-equivalent info or `navigator.userAgentData`); Tauri callers
 * additionally pass `webview2Version`. Node-only fallbacks are used for the
 * fields Node *can* see (CPU model, OS, arch) so unit tests can call this
 * without a browser.
 *
 * @param {Partial<MachineDescriptor>} [overrides]
 * @returns {MachineDescriptor}
 */
export function captureMachineDescriptor(overrides = {}) {
  const cpuInfo = cpus();
  const descriptor = {
    cpu: cpuInfo[0]?.model ?? "unknown-cpu",
    cpuCount: cpuInfo.length,
    totalMemMb: Math.round(totalmem() / (1024 * 1024)),
    os: platform(),
    osBuild: release(),
    arch: arch(),
    gpu: "unknown-gpu",
    driver: "unknown-driver",
    webview2Version: null,
    ...overrides,
  };
  return descriptor;
}

/**
 * Validates a machine descriptor has every required field populated
 * (non-empty, not the "unknown-*" placeholder). Throws with the missing
 * field names so a run fails loudly instead of shipping anonymous numbers.
 * @param {MachineDescriptor} descriptor
 */
export function assertDescriptorComplete(descriptor) {
  const missing = REQUIRED_DESCRIPTOR_FIELDS.filter((field) => {
    const value = descriptor[field];
    return (
      value === undefined || value === null || value === "" || String(value).startsWith("unknown-")
    );
  });
  if (missing.length > 0) {
    throw new Error(
      `[bench] machine descriptor incomplete, refusing to report anonymous numbers: missing ${missing.join(", ")}`,
    );
  }
}
