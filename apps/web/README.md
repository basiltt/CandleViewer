# @candleviewer/web

React SPA (Vite + React 18 + TS). E02-T04 ships a bootable skeleton with one
placeholder route — the real route tree (`12-sitemap.md`), auth/RBAC guards,
env badge and global shortcuts are **E10**.

- `src/routes/` — route components (`PlaceholderRoute` only, for now).
- `src/features/<feature>/` — feature-sliced modules (empty).
- `src/lib/{ws,state,auth}/` — WS client, Zustand/Jotai state, auth helpers
  (empty; see each directory's `README.md` for ownership).
- `e2e/` — Playwright web smoke + `@axe-core/playwright` a11y spec.
- `test/` — Vitest + React Testing Library component tests.

## Scripts

- `pnpm --filter @candleviewer/web dev` — Vite dev server.
- `pnpm --filter @candleviewer/web build` — production build to `dist/`.
- `pnpm --filter @candleviewer/web test` / `test:cov` — Vitest, ≥80% gate.
- `pnpm --filter @candleviewer/web e2e` — Playwright smoke + a11y specs
  (builds and previews the app first).
- `pnpm --filter @candleviewer/web size` — size-limit budget check
  (≤8 MB gzipped initial bundle, Constitution §9 #15,
  `06-performance-and-load-standard.md` budget #9).
