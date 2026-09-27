// C-2.16 enforcement: packages/chart-engine must not import React, the DOM,
// `fetch`, or any Bybit/exchange-specific module. Violations fail lint with a
// message citing C-2.16 (ticket E02-T03 acceptance criterion #2).
import tseslint from "typescript-eslint";
import globals from "globals";
import baseConfig from "@candleviewer/config/eslint";

/** @type {import("eslint").Linter.Config[]} */
export default tseslint.config(
  ...baseConfig,
  {
    ignores: ["dist/**", "coverage/**", "bench/results.json", "bench/baseline.json"],
  },
  ...tseslint.configs.recommended,
  {
    files: ["**/*.ts"],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    files: ["bench/run-bench.mjs", "bench/scenes/run-scene-a.mjs", "bench/scenes/scene-a.mjs"],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
  {
    files: ["src/**/*.ts", "bench/**/*.ts"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "react",
              message: "C-2.16: packages/chart-engine must not depend on React.",
            },
            {
              name: "react-dom",
              message: "C-2.16: packages/chart-engine must not depend on React.",
            },
          ],
          patterns: [
            {
              group: ["**/exchange/**", "**/bybit/**"],
              message: "C-2.16: packages/chart-engine must have no Bybit/exchange knowledge.",
            },
          ],
        },
      ],
      "no-restricted-globals": [
        "error",
        { name: "fetch", message: "C-2.16: packages/chart-engine must not call fetch." },
        { name: "document", message: "C-2.16: no DOM globals in src/core or src/layers." },
        { name: "window", message: "C-2.16: no DOM globals in src/core or src/layers." },
      ],
    },
  },
  {
    files: ["src/worker/**/*.ts"],
    rules: {
      // The worker glue is the one place OffscreenCanvas/postMessage globals
      // are expected; core/layers stay DOM-free (C-2.16).
      "no-restricted-globals": "off",
    },
  },
);
