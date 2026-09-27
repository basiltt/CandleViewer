// Root ESLint flat config — thin wrapper around the shared preset in
// packages/config so root-level files (scripts/, package.json) are linted
// with the same rules as workspace packages.
import { baseConfig } from "./packages/config/eslint.config.mjs";

export default [
  ...baseConfig,
  {
    // Root-level tooling scripts run under plain Node (no bundler globals
    // config), so declare the Node global env directly rather than pulling
    // in the `globals` package for one env object (E02-T07).
    files: [
      "scripts/**/*.{mjs,cjs,js}",
      "packages/*/scripts/**/*.{mjs,cjs,js}",
      "*.config.{mjs,cjs,js}",
    ],
    languageOptions: {
      globals: {
        process: "readonly",
        console: "readonly",
        __dirname: "readonly",
        __filename: "readonly",
        module: "readonly",
        require: "readonly",
        URL: "readonly",
      },
    },
  },
  {
    ignores: ["**/dist/**", "**/coverage/**", "**/.turbo/**", "**/node_modules/**"],
  },
];
