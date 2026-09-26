// Root ESLint flat config — thin wrapper around the shared preset in
// packages/config so root-level files (scripts/, package.json) are linted
// with the same rules as workspace packages.
import { baseConfig } from "./packages/config/eslint.config.mjs";

export default [
  ...baseConfig,
  {
    ignores: ["**/dist/**", "**/coverage/**", "**/.turbo/**", "**/node_modules/**"],
  },
];
