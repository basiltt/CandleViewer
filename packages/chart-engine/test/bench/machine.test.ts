import { describe, expect, it } from "vitest";
import {
  captureMachineDescriptor,
  assertDescriptorComplete,
  REQUIRED_DESCRIPTOR_FIELDS,
} from "../../bench/machine.mjs";

describe("machine descriptor (ticket: a run missing any field fails)", () => {
  it("captures Node-visible fields (cpu, os, osBuild, arch) without overrides", () => {
    const descriptor = captureMachineDescriptor();
    expect(descriptor.cpu).not.toBe("");
    expect(descriptor.os).not.toBe("");
    expect(descriptor.cpuCount).toBeGreaterThan(0);
  });

  it("accepts overrides for GPU/driver/webview2 (browser-only fields)", () => {
    const descriptor = captureMachineDescriptor({ gpu: "NVIDIA GTX 1650", driver: "31.0.15" });
    expect(descriptor.gpu).toBe("NVIDIA GTX 1650");
    expect(descriptor.driver).toBe("31.0.15");
  });

  it("throws listing missing fields when gpu/driver are left as unknown placeholders", () => {
    const descriptor = captureMachineDescriptor();
    expect(() => assertDescriptorComplete(descriptor)).toThrowError(/gpu, driver/);
  });

  it("does not throw once every required field is populated", () => {
    const descriptor = captureMachineDescriptor({ gpu: "Iris Xe", driver: "1.2.3" });
    for (const field of REQUIRED_DESCRIPTOR_FIELDS) {
      expect(descriptor[field]).toBeTruthy();
    }
    expect(() => assertDescriptorComplete(descriptor)).not.toThrow();
  });
});
