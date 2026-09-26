import { defineConfig } from "vitest/config";
import { vitestPreset } from "@candleviewer/config/vitest";

export default defineConfig({
  test: {
    ...vitestPreset.test,
    include: ["test/**/*.test.mjs"],
    coverage: {
      ...vitestPreset.test.coverage,
      include: ["src/**/*.mjs", "scripts/**/*.mjs"],
      exclude: ["src/index.mjs"],
    },
  },
});
