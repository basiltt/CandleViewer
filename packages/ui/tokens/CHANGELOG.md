# Changelog — `packages/ui/tokens`

Versioned independently from `@candleviewer/ui` (docs/plan/16-design-system-brief.md #11:
"the `tokens/` directory is versioned independently ... since a token-only
change should be shippable and reviewable without touching component code").

## [0.1.0] - 2026-09-29

### Added

- Initial authored token source of truth: `primitives.tokens.json` (Tier 1),
  `semantic-dark.tokens.json` (Tier 2 source of truth), `semantic-light.tokens.json`,
  `semantic-hc.tokens.json` (theme overlays), `themes.json` (theme/density
  composition).
- Style Dictionary multi-target build (`scripts/build-tokens.mjs`,
  `style-dictionary.config.json`) producing all six artefacts from
  `docs/plan/16-design-system-brief.md#11`: three theme CSS files, the typed
  TS token object, the WebGL engine uniform buffer, and the Electron main
  JSON.
- Custom Style Dictionary formats `json/flat-rgba`, `json/flat`,
  `typescript/nested-object` in `tools/style-dictionary/formats/`.
- Theme-parity (`TOKENS-E001`), alias-resolution (`TOKENS-E002`), and
  engine-category (`TOKENS-E003`) build-time checks.
- ESLint `candleviewer/no-raw-design-values` rule forbidding raw hex colours
  and raw `px` literals in `packages/ui/src/**`.
