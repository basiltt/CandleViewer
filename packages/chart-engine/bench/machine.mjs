// Machine descriptor capture (E06-K01 ticket "The machine is always
// identified" AC): CPU, GPU, driver version, OS build, and (Tauri) WebView2
// version. A run missing any required field fails rather than reporting
// anonymous numbers.
import { cpus, totalmem, platform, release, arch } from "node:os";
import { execFileSync } from "node:child_process";

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

// ---------------------------------------------------------------------------
// E06-T01 matrix extension: full version manifest (additive; the descriptor
// above is unchanged so every existing report/test keeps working).
// ---------------------------------------------------------------------------

/**
 * Windows-only GPU/driver probe via the OS video controller list. Used as the
 * runtime-independent fallback so the descriptor's required `gpu`/`driver`
 * fields can be filled for Electron/Tauri/Chromium alike. Returns null off
 * Windows or on any failure (the caller then relies on runtime-reported info
 * and `assertDescriptorComplete` fails loudly if still unknown).
 * @returns {{ gpu: string, driver: string } | null}
 */
export function probeWindowsGpu() {
  if (platform() !== "win32") return null;
  try {
    const out = execFileSync(
      "powershell.exe",
      [
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion | ConvertTo-Json -Compress",
      ],
      { encoding: "utf8", timeout: 15_000 },
    );
    const parsed = JSON.parse(out);
    const list = Array.isArray(parsed) ? parsed : [parsed];
    // Prefer a discrete/real adapter over the basic render driver.
    const pick =
      list.find((g) => g?.Name && !/basic render|remote display/i.test(g.Name)) ?? list[0];
    if (!pick?.Name) return null;
    return { gpu: String(pick.Name), driver: String(pick.DriverVersion ?? "") };
  } catch {
    return null;
  }
}

/**
 * @typedef {{
 *   schema: "cv-version-manifest/1",
 *   machine: MachineDescriptor,
 *   runtime: "chromium" | "electron" | "tauri",
 *   versions: {
 *     node: string,
 *     electron: string | null,
 *     chromium: string | null,
 *     tauri: string | null,
 *     webview2: string | null,
 *     playwright: string | null,
 *   },
 *   flagSet: { name: string, flags: string[] },
 * }} VersionManifest
 */

/**
 * Builds the complete per-run version manifest required by E06-T01 (CPU, GPU,
 * driver, OS build, Electron/Chromium/Tauri/WebView2/Node versions, flag set).
 * Runtime-specific values arrive from the runtime itself (never guessed).
 *
 * @param {{
 *   runtime: VersionManifest["runtime"],
 *   machine?: Partial<MachineDescriptor>,
 *   versions?: Partial<VersionManifest["versions"]>,
 *   flagSet?: { name: string, flags: string[] },
 *   useOsGpuProbe?: boolean,
 * }} opts
 * @returns {VersionManifest}
 */
export function captureVersionManifest(opts) {
  const os = opts.useOsGpuProbe === false ? null : probeWindowsGpu();
  const machine = captureMachineDescriptor({
    ...(os ?? {}),
    ...(opts.machine ?? {}),
    webview2Version: opts.versions?.webview2 ?? opts.machine?.webview2Version ?? null,
  });
  return {
    schema: "cv-version-manifest/1",
    machine,
    runtime: opts.runtime,
    versions: {
      node: process.versions.node,
      electron: null,
      chromium: null,
      tauri: null,
      webview2: null,
      playwright: null,
      ...(opts.versions ?? {}),
    },
    flagSet: opts.flagSet ?? { name: "unspecified", flags: [] },
  };
}

/**
 * Per-runtime required version fields: a Tauri run without a WebView2 version
 * is meaningless (ADR-0011: the arm's whole point is that this version is
 * OS-updated), and an Electron run without Electron+Chromium is unattributable.
 * @param {VersionManifest} manifest
 * @returns {string[]} names of missing fields (empty when complete)
 */
export function missingManifestFields(manifest) {
  const need = {
    chromium: ["chromium"],
    electron: ["electron", "chromium"],
    tauri: ["tauri", "webview2"],
  }[manifest.runtime];
  return need.filter((k) => !manifest.versions[k]);
}
