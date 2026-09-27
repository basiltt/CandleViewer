# @candleviewer/ui

Design system: tokens, primitives, trading components. Storybook 8 with the
a11y addon; Style Dictionary token build. Depends only on
`@candleviewer/protocol` and `@candleviewer/chart-engine` — never on `apps/*`
(C-3.5).

- `tokens/` — DTCG source JSON (contract from E02-D01), verified by
  `tokens/tests/verify_tokens.py`.
- `src/tokens/`, `src/primitives/`, `src/components/` — TS/React surface;
  E02-T03 ships only a `Placeholder` primitive to prove the harness. Real
  content is E05's scope.

## Scripts

- `pnpm --filter @candleviewer/ui build` — runs `build:tokens` (Style
  Dictionary → `dist/tokens/*.css`) then the tsup build.
- `pnpm --filter @candleviewer/ui storybook` — dev server with the a11y addon.
- `pnpm --filter @candleviewer/ui test` / `test:cov` — Vitest, ≥80% gate.
