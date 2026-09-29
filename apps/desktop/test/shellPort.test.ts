import { describe, expect, it } from "vitest";
import { HARDENED_WEB_PREFERENCES } from "../src/main/shellPort";

describe("HARDENED_WEB_PREFERENCES", () => {
  it("has every hardening flag set to the secure value", () => {
    expect(HARDENED_WEB_PREFERENCES).toEqual({
      contextIsolation: true,
      nodeIntegration: false,
      nodeIntegrationInWorker: false,
      nodeIntegrationInSubFrames: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      experimentalFeatures: false,
    });
    expect(HARDENED_WEB_PREFERENCES).not.toHaveProperty("enableRemoteModule");
  });
});
