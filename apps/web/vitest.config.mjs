import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { vitestPreset } from "@candleviewer/config/vitest";

export default defineConfig({
  plugins: [react()],
  test: {
    ...vitestPreset.test,
    environment: "jsdom",
    globals: false,
    setupFiles: ["./test/setup.ts"],
    include: ["test/**/*.test.{ts,tsx}"],
    coverage: {
      ...vitestPreset.test.coverage,
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/main.tsx", "src/**/*.stories.tsx"],
      thresholds: {
        lines: 80,
        statements: 80,
        functions: 80,
        branches: 70,
      },
    },
  },
});
