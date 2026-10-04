import type { EngineHandle } from "@candleviewer/chart-engine";

/** Live engine instances mounted by the chart host adapter (WebGL surfaces). */
const engines = new Set<Pick<EngineHandle, "setTheme">>();

export function registerEngine(engine: Pick<EngineHandle, "setTheme">): () => void {
  engines.add(engine);
  return () => engines.delete(engine);
}

export function registeredEngines(): readonly Pick<EngineHandle, "setTheme">[] {
  return [...engines];
}
