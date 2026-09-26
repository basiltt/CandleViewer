// Shared ESLint flat config (Constitution §9 #1: --max-warnings=0).
// Consumers import this as the base and extend with framework-specific
// plugins (react, react-hooks) in their own eslint.config.mjs.
import js from "@eslint/js";
import jsxA11y from "eslint-plugin-jsx-a11y";
import { noRestrictedImportsRuleSet } from "./no-restricted-imports.mjs";

/** @type {import("eslint").Linter.Config[]} */
export const baseConfig = [
  js.configs.recommended,
  {
    plugins: {
      "jsx-a11y": jsxA11y,
    },
    rules: {
      ...jsxA11y.configs.recommended.rules,
      "no-restricted-imports": ["error", noRestrictedImportsRuleSet],
    },
  },
  {
    ignores: [
      "**/dist/**",
      "**/coverage/**",
      "**/.turbo/**",
      "**/node_modules/**",
      "**/src/generated/**",
    ],
  },
];

export default baseConfig;
