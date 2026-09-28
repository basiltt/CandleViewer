import { describe, expect, it } from "vitest";
import playwrightConfig from "../e2e/playwright.config";

// Bug #1527 (E03-T06-B1, parent #107 AC3): apps/desktop's Electron
// Playwright config had no failure-artifact capture configured either;
// this config has no retries, so "retain-on-failure" (not
// "on-first-retry") is required for trace to be produced on a single
// failing run.
describe("apps/desktop e2e playwright-electron config", () => {
  it("enables trace capture on failure", () => {
    expect(playwrightConfig.use?.trace).toBe("retain-on-failure");
  });

  it("enables screenshot capture on failure", () => {
    expect(playwrightConfig.use?.screenshot).toBe("only-on-failure");
  });

  it("enables video capture on failure", () => {
    expect(playwrightConfig.use?.video).toBe("retain-on-failure");
  });
});
