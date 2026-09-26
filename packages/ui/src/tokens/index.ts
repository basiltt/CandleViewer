// Re-exports the generated token build metadata. The DTCG token source lives
// in packages/ui/tokens/ (contract from E02-D01) and is compiled to CSS
// custom properties via `pnpm --filter @candleviewer/ui build:tokens`
// (style-dictionary.config.json). Real token TS bindings land with E05.

/** Bumped whenever the DTCG token schema shape changes. */
export const TOKEN_SCHEMA_VERSION = 1;
