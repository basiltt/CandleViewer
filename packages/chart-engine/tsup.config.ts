import { defineConfig } from "tsup";

// tsup build: ESM only, workspace-consumable, semver'd per docs/plan/20-architecture.md §7.
export default defineConfig({
  entry: {
    index: "src/index.ts",
    bench: "bench/harness.ts",
  },
  format: ["esm"],
  dts: true,
  sourcemap: true,
  clean: true,
  target: "es2022",
  platform: "neutral",
});
