import { describe, expect, it, vi, beforeEach } from "vitest";

const appendSwitch = vi.fn();
const getGPUInfo = vi.fn();

vi.mock("electron", () => ({
  app: { commandLine: { appendSwitch }, getGPUInfo },
}));

describe("applyGpuFlags", () => {
  it("applies exactly the flags documented in GPU_FLAGS.md", async () => {
    const { applyGpuFlags } = await import("../src/main/gpu");
    appendSwitch.mockClear();
    applyGpuFlags();
    expect(appendSwitch).toHaveBeenCalledWith("enable-gpu-rasterization");
    expect(appendSwitch).toHaveBeenCalledWith("disable-features", "CalculateNativeWinOcclusion");
  });

  it("never applies disable-gpu-sandbox or ignore-gpu-blocklist", async () => {
    const { applyGpuFlags } = await import("../src/main/gpu");
    appendSwitch.mockClear();
    applyGpuFlags();
    const calls = appendSwitch.mock.calls.map((call) => call[0]);
    expect(calls).not.toContain("disable-gpu-sandbox");
    expect(calls).not.toContain("ignore-gpu-blocklist");
  });
});

describe("probeGpu", () => {
  beforeEach(() => {
    getGPUInfo.mockReset();
  });

  it("reports hardware-accelerated when a GPU device is present", async () => {
    getGPUInfo.mockResolvedValue({
      gpuDevice: [{ vendorId: 1, deviceId: 2 }],
      auxAttributes: { glVendor: "NVIDIA", glRenderer: "NVIDIA GeForce" },
    });
    const { probeGpu } = await import("../src/main/gpu");
    const result = await probeGpu();
    expect(result).toEqual({
      vendor: "NVIDIA",
      renderer: "NVIDIA GeForce",
      hardwareAccelerated: true,
      webgl2CapabilityParity: true,
    });
  });

  it("reports not-hardware-accelerated when no GPU device is present", async () => {
    getGPUInfo.mockResolvedValue({ gpuDevice: [], auxAttributes: {} });
    const { probeGpu } = await import("../src/main/gpu");
    const result = await probeGpu();
    expect(result.hardwareAccelerated).toBe(false);
    expect(result.webgl2CapabilityParity).toBe(false);
  });

  it("degrades to an unknown/false result rather than throwing when the probe itself fails", async () => {
    getGPUInfo.mockRejectedValue(new Error("boom"));
    const { probeGpu } = await import("../src/main/gpu");
    const result = await probeGpu();
    expect(result).toEqual({
      vendor: "unknown",
      renderer: "unknown",
      hardwareAccelerated: false,
      webgl2CapabilityParity: false,
    });
  });
});
