# @candleviewer/desktop

Electron shell wrapping `apps/web`'s build. **No business logic** (C-3.5) —
that stays behind the `ShellPort` abstraction in `src/main/shellPort.ts`
because ADR-0011 (Electron vs Tauri) is `proposed`, not decided.

- `src/main/` — main process: window creation, hardening, CSP header,
  startup/audit logging.
- `src/preload/` — context-isolated preload; exposes exactly one namespaced
  object, `window.cv`, built from an explicit IPC channel allow-list (empty
  at E02-T04; editing `allowList.ts` is code-owned by the security engineer,
  trust boundary B4, `20-architecture.md` §2.2).
- `e2e/` — Playwright-Electron: main-window smoke spec and the hardening
  assertion test that reads live `webPreferences` at runtime.

## Hardened defaults (asserted, not just configured)

`contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`,
`webSecurity: true`; `window.open` denied via `setWindowOpenHandler`;
`will-navigate` restricted to the app origin. `e2e/hardening.spec.ts` fails
if any flag drifts.

## Scripts

- `pnpm --filter @candleviewer/desktop build` — compiles `src/` to `dist/`.
- `pnpm --filter @candleviewer/desktop dev` — build then launch Electron.
- `pnpm --filter @candleviewer/desktop e2e` — Playwright-Electron specs
  (requires `build` to have run first).
- `pnpm --filter @candleviewer/desktop build:installer` — electron-builder
  packaging (real signing/notarization/auto-update land in E10).

## Out of scope (E10)

Route tree, auth/RBAC guards, env badge, global shortcut registry,
auto-update, crash reporting, GPU flag tuning (depends on E06).
