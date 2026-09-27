import { defineConfig } from "@playwright/test";

// apps/desktop Playwright-Electron config (E02-T04): hardening assertion +
// main-window smoke specs.
export default defineConfig({
  testDir: ".",
  timeout: 60_000,
  retries: 0,
  workers: 1,
});
