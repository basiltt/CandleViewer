import { defineConfig } from "vitest/config";
import { vitestPreset } from "@candleviewer/config/vitest";

export default defineConfig({
  test: {
    ...vitestPreset.test,
    include: ["test/**/*.test.ts"],
    coverage: {
      ...vitestPreset.test.coverage,
      include: ["src/**/*.ts", "bench/**/*.ts"],
      exclude: ["src/**/index.ts"],
      // Constitution §9 #4: chart-engine coverage floor is >=85%.
      thresholds: {
        lines: 85,
        statements: 85,
        functions: 85,
        branches: 75,
      },
    },
  },
});
