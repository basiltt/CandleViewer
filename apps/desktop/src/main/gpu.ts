import { app } from "electron";

/**
 * GPU command-line switches applied before `app.whenReady()`. Every entry
 * here must have a matching row in `apps/desktop/GPU_FLAGS.md` — this file
 * is the single place `appendSwitch` is called so the documented list can
 * never drift from what actually runs.
 */
export function applyGpuFlags(): void {
  app.commandLine.appendSwitch("enable-gpu-rasterization");
  app.commandLine.appendSwitch("disable-features", "CalculateNativeWinOcclusion");
}

export interface GpuProbeResult {
  readonly vendor: string;
  readonly renderer: string;
  readonly hardwareAccelerated: boolean;
  readonly webgl2CapabilityParity: boolean;
}

/**
 * Reads Electron's `app.getGPUInfo("basic")` result into the typed shape the
 * renderer consumes via `ShellPort.gpu.info()`. `webgl2CapabilityParity` is
 * conservatively `false` unless hardware acceleration is confirmed — the
 * renderer treats an unknown/false result as "enter degraded-2d", never the
 * other way round (`20-architecture.md` F15).
 */
export async function probeGpu(): Promise<GpuProbeResult> {
  try {
    const info = (await app.getGPUInfo("basic")) as {
      gpuDevice?: ReadonlyArray<{ vendorId?: number; deviceId?: number }>;
      auxAttributes?: { glRenderer?: string; glVendor?: string };
    };
    const hardwareAccelerated = Boolean(info.gpuDevice && info.gpuDevice.length > 0);
    return {
      vendor: info.auxAttributes?.glVendor ?? "unknown",
      renderer: info.auxAttributes?.glRenderer ?? "unknown",
      hardwareAccelerated,
      webgl2CapabilityParity: hardwareAccelerated,
    };
  } catch {
    return {
      vendor: "unknown",
      renderer: "unknown",
      hardwareAccelerated: false,
      webgl2CapabilityParity: false,
    };
  }
}
