import globals from "globals";
import baseConfig from "@candleviewer/config/eslint";

/** @type {import("eslint").Linter.Config[]} */
export default [
  ...baseConfig,
  {
    ignores: ["coverage/**", "raw/**", "golden/**"],
  },
  {
    files: ["**/*.mjs"],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
];
