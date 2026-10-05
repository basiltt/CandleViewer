import { resolve } from "node:path";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { vitestPreset } from "@candleviewer/config/vitest";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@candleviewer/ui": resolve(import.meta.dirname, "../../packages/ui/src/index.ts"),
      "@candleviewer/chart-engine": resolve(
        import.meta.dirname,
        "../../packages/chart-engine/src/index.ts",
      ),
      "@candleviewer/protocol": resolve(
        import.meta.dirname,
        "../../packages/protocol/src/index.ts",
      ),
    },
  },
  test: {
    ...vitestPreset.test,
    environment: "jsdom",
    globals: false,
    setupFiles: ["./test/setup.ts"],
    include: ["test/**/*.test.{ts,tsx}"],
    coverage: {
      ...vitestPreset.test.coverage,
      // #1535: do not wipe coverage/ at start (it raced the .tmp writer on a cold
      // cache); the test:cov script pre-creates coverage/.tmp instead.
      clean: false,
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/main.tsx", "src/**/*.stories.tsx", "src/shell/ShellPort.ts"],
      thresholds: {
        lines: 80,
        statements: 80,
        functions: 80,
        branches: 70,
      },
    },
  },
});
