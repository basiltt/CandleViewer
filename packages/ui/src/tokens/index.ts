// Re-exports the generated token build metadata. The DTCG token source lives
// in packages/ui/tokens/ (contract from E02-D01) and is compiled to CSS
// custom properties, a typed TS object, WebGL engine uniforms, and an
// Electron main JSON via `pnpm --filter @candleviewer/ui build:tokens`
// (scripts/build-tokens.mjs + style-dictionary.config.json — E05-T01).
//
// Components should import the generated `build/ts/tokens.ts` directly
// (not re-exported from here) once E05's component work lands — see
// packages/ui/README.md's "Token build" section for the full artefact
// table and the `candleviewer/no-raw-design-values` ESLint rule that
// enforces it.

/** Bumped whenever the DTCG token schema shape changes. */
export const TOKEN_SCHEMA_VERSION = 1;
