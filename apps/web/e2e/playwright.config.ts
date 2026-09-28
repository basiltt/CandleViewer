import { defineConfig } from "@playwright/test";

// apps/web Playwright config — smoke + a11y specs only (E02-T04).
export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  // E03-T06: one automatic retry in CI (each retry recorded in the reporter
  // output for E03-Q03's deferred quarantine automation); local runs stay
  // deterministic (no retry) so failures aren't masked during development.
  retries: process.env["CI"] ? 1 : 0,
  // E03-T06-B1 (bug #1527): capture failure artifacts so AC3's
  // "trace/video/screenshot uploaded on failure" scenario is actually
  // satisfied — defaults are "off"; "on-first-retry" / "retain-on-failure"
  // only materialize files when a spec actually fails.
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command: "npx vite preview --port 4173 --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env["CI"],
    cwd: "..",
    timeout: 120_000,
  },
});
