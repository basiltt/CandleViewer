import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// apps/web Vite config — placeholder route only (E02-T04). Real routing,
// aliasing and env handling land in E10.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
