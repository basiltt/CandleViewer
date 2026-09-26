import { defineConfig } from "vitest/config";
import { vitestPreset } from "./vitest.preset.mjs";

export default defineConfig({
  test: {
    ...vitestPreset.test,
    include: ["tests/**/*.test.mjs"],
    coverage: {
      ...vitestPreset.test.coverage,
      include: ["*.mjs", "src/**/*.mjs"],
      // src/index.mjs is a pure re-export barrel with no branching logic
      // (exercised indirectly via the direct-import tests); eslint.config.mjs
      // is declarative wiring, covered by `pnpm lint` actually running it.
      exclude: ["src/index.mjs", "eslint.config.mjs", "vitest.config.mjs"],
    },
  },
});
