import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// apps/web Vite config — placeholder route only (E02-T04). Real routing,
// aliasing and env handling land in E10.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@candleviewer/protocol": resolve(
        import.meta.dirname,
        "../../packages/protocol/src/index.ts",
      ),
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
