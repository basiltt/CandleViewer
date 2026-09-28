import { describe, expect, it } from "vitest";
import playwrightConfig from "../e2e/playwright.config";

// Bug #1527 (E03-T06-B1, parent #107 AC3): Playwright must capture
// trace/screenshot/video on failure so the "e2e failure produces a
// debuggable artifact" scenario is actually satisfied — Playwright's
// defaults are all "off", so the upload-artifact step in
// _job-e2e.yml had nothing to upload.
describe("apps/web e2e playwright config", () => {
  it("enables trace capture for retried/failed runs", () => {
    expect(playwrightConfig.use?.trace).toBe("on-first-retry");
  });

  it("enables screenshot capture on failure", () => {
    expect(playwrightConfig.use?.screenshot).toBe("only-on-failure");
  });

  it("enables video capture on failure", () => {
    expect(playwrightConfig.use?.video).toBe("retain-on-failure");
  });
});
