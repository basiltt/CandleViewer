import { defineConfig } from "@playwright/test";

// apps/web Playwright config — smoke + a11y specs only (E02-T04).
export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:4173",
  },
  webServer: {
    command: "npx vite preview --port 4173 --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env["CI"],
    cwd: "..",
    timeout: 120_000,
  },
});
