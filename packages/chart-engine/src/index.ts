// Public entrypoint for @candleviewer/chart-engine.
// Scaffold only (E02-T03): rendering, layers and worker wiring land in E06/E11.
// C-2.16: this package must never import React, DOM globals, `fetch`, or any
// Bybit/exchange-specific module. `pnpm --filter @candleviewer/chart-engine lint`
// enforces this via the shared `no-restricted-imports` / `no-restricted-globals`
// rule set in packages/config/eslint.config.mjs.

/**
 * Engine version marker, bumped alongside the package version. Consumers can
 * assert on this in integration smoke tests without depending on internals.
 */
export const CHART_ENGINE_VERSION = "0.1.0";

export type { EngineHandle } from "./core/handle.js";
export { createEngine } from "./core/handle.js";
export type { EngineOptions, EngineStats, EngineTheme } from "./core/handle.js";
