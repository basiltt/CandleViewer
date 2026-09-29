import { describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({
  app: { getVersion: vi.fn().mockReturnValue("0.1.0") },
}));

describe("update channel stub (SR-115)", () => {
  it("reports auto-update as disabled", async () => {
    const { isAutoUpdateEnabled } = await import("../src/main/updateChannel");
    expect(isAutoUpdateEnabled()).toBe(false);
  });

  it("getCurrentVersion reads the packaged app version, nothing else", async () => {
    const { getCurrentVersion } = await import("../src/main/updateChannel");
    expect(getCurrentVersion()).toBe("0.1.0");
  });

  it("checkForUpdate never attempts a download and reports the disabled reason", async () => {
    const { checkForUpdate, UPDATE_CHANNEL_DISABLED_REASON } =
      await import("../src/main/updateChannel");
    const result = checkForUpdate();
    expect(result).toEqual({ state: "error", reason: UPDATE_CHANNEL_DISABLED_REASON });
  });

  it("applyUpdate always throws — there is no installer path reachable", async () => {
    const { applyUpdate, UPDATE_CHANNEL_DISABLED_REASON } =
      await import("../src/main/updateChannel");
    expect(() => applyUpdate()).toThrow(UPDATE_CHANNEL_DISABLED_REASON);
  });
});
