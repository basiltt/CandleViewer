import { defineConfig } from "vitest/config";
import { vitestPreset } from "@candleviewer/config/vitest";

export default defineConfig({
  test: {
    ...vitestPreset.test,
    include: ["test/**/*.test.ts"],
    coverage: {
      ...vitestPreset.test.coverage,
      include: ["src/**/*.ts"],
      exclude: ["src/main/index.ts", "src/main/logger.ts", "src/preload/index.ts"],
      thresholds: {
        lines: 80,
        statements: 80,
        functions: 80,
        branches: 70,
      },
    },
  },
});
