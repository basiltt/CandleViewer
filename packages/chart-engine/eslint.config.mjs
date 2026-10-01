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
    files: [
      "bench/run-bench.mjs",
      "bench/scenes/run-scene-a.mjs",
      "bench/scenes/scene-a.mjs",
      "bench/scenes/run-scene-b.mjs",
      "bench/scenes/scene-b.mjs",
      "bench/scenes/atlas.mjs",
    ],
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
            {
              group: ["**/spike/**"],
              message:
                "E06-X02: the promoted benchmark harness must never import from a spike-only " +
                "(throwaway prototype) path. See tools/ci/check_spike_containment.py.",
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
    // The bench harness/runner/driver `.mjs` files are not covered by the
    // `**/*.ts` glob above but are exactly the "promoted harness" this
    // boundary protects (E06-X02 acceptance criterion "The harness does not
    // depend on the prototype").
    files: ["bench/**/*.mjs"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/spike/**"],
              message:
                "E06-X02: the promoted benchmark harness must never import from a spike-only " +
                "(throwaway prototype) path. See tools/ci/check_spike_containment.py.",
            },
          ],
        },
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
