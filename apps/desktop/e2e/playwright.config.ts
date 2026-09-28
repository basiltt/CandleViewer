import { defineConfig } from "@playwright/test";

// apps/desktop Playwright-Electron config (E02-T04): hardening assertion +
// main-window smoke specs.
export default defineConfig({
  testDir: ".",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  // E03-T06-B1 (bug #1527): capture failure artifacts (AC3). No retries
  // configured here, so "on-first-retry" would never fire — use
  // "retain-on-failure" for trace too so a single failed run still uploads.
  use: {
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
});
