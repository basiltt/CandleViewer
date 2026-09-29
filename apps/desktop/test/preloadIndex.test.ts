import { describe, expect, it, vi, beforeEach } from "vitest";

const invokeMock = vi.fn().mockResolvedValue("ok");
const exposeInMainWorldMock = vi.fn();

vi.mock("electron", () => ({
  contextBridge: { exposeInMainWorld: exposeInMainWorldMock },
  ipcRenderer: { invoke: invokeMock },
}));

describe("preload bridge", () => {
  beforeEach(() => {
    vi.resetModules();
    invokeMock.mockClear();
    exposeInMainWorldMock.mockClear();
  });

  it("exposes exactly window.cv with the three named methods, no generic invoke", async () => {
    await import("../src/preload/index");
    expect(exposeInMainWorldMock).toHaveBeenCalledTimes(1);
    const [name, cv] = exposeInMainWorldMock.mock.calls[0] as [string, Record<string, unknown>];
    expect(name).toBe("cv");
    expect(Object.keys(cv).sort()).toEqual(["gpuInfo", "keychainGetKekHandle", "updatesCheck"]);
    expect(cv["ipcRenderer"]).toBeUndefined();
    expect(cv["invoke"]).toBeUndefined();
  });

  it("gpuInfo() invokes exactly the cv:gpu:info channel with no caller-supplied args", async () => {
    const preload = await import("../src/preload/index");
    void preload;
    const [, cv] = exposeInMainWorldMock.mock.calls[0] as [string, Record<string, () => unknown>];
    await cv["gpuInfo"]?.();
    expect(invokeMock).toHaveBeenCalledWith("cv:gpu:info");
  });

  it("keychainGetKekHandle() invokes exactly the cv:keychain:getKekHandle channel", async () => {
    await import("../src/preload/index");
    const [, cv] = exposeInMainWorldMock.mock.calls[0] as [string, Record<string, () => unknown>];
    await cv["keychainGetKekHandle"]?.();
    expect(invokeMock).toHaveBeenCalledWith("cv:keychain:getKekHandle");
  });

  it("updatesCheck() invokes exactly the cv:updates:check channel", async () => {
    await import("../src/preload/index");
    const [, cv] = exposeInMainWorldMock.mock.calls[0] as [string, Record<string, () => unknown>];
    await cv["updatesCheck"]?.();
    expect(invokeMock).toHaveBeenCalledWith("cv:updates:check");
  });
});
