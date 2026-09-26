// Scaffold engine handle (E02-T03). Real GL/layer wiring lands in E06 (spike)
// and E11 (engine core). No DOM globals, no React, no fetch here (C-2.16).

export interface EngineHandle {
  /** Releases pooled GPU resources and worker subscriptions. */
  dispose(): void;
}

/**
 * Creates a placeholder engine handle. Intentionally does nothing beyond
 * proving the export surface + dispose() contract that E06/E11 build on.
 */
export function createEngine(): EngineHandle {
  let disposed = false;
  return {
    dispose(): void {
      disposed = true;
      void disposed;
    },
  };
}
