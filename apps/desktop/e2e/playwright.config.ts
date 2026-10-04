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
  // hotkeys.spec.ts loads the built web app via CV_DEV_SERVER_URL; serve it with `vite preview`
  // (requires `pnpm --filter @candleviewer/web build` first, as the web e2e job does).
  webServer: {
    command: "npx vite preview --port 4173 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env["CI"],
    cwd: "../web",
    timeout: 120_000,
  },
  use: {
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
});
