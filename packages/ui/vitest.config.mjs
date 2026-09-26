import { defineConfig } from "vitest/config";
import { vitestPreset } from "@candleviewer/config/vitest";

export default defineConfig({
  test: {
    ...vitestPreset.test,
    include: ["test/**/*.test.{ts,tsx}"],
    coverage: {
      ...vitestPreset.test.coverage,
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/index.ts", "src/components/index.ts", "src/**/*.stories.tsx"],
      thresholds: {
        lines: 80,
        statements: 80,
        functions: 80,
        branches: 70,
      },
    },
  },
});
