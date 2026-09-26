// Stub `no-restricted-imports` rule set (E02-T01 scope).
// E02-T06 (module-boundary / dependency-cruiser ticket) extends this with the
// per-package boundary rules derived from CONSTITUTION.md §3's module table.
// Kept as a small, typed export so E02-T06 can import and extend it rather
// than re-declaring the rule shape.

/** @typedef {{ paths?: Array<{ name: string, message: string }>, patterns?: Array<{ group: string[], message: string }> }} RestrictedImportsRuleSet */

/** @type {RestrictedImportsRuleSet} */
export const noRestrictedImportsRuleSet = {
  paths: [
    {
      name: "lodash",
      message: "Use native ES2022+ methods or a scoped lodash/<fn> import instead of the full package.",
    },
  ],
  patterns: [
    {
      group: ["**/dist/**", "**/src/generated/**/*.internal"],
      message: "Import from a package's public entrypoint, not its build output or internal generated files.",
    },
  ],
};

export default noRestrictedImportsRuleSet;
