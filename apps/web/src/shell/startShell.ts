/**
 * Top-level shell start: runs the REST bootstrap and connects the `system`
 * WS topic concurrently (performance note: "the WS connects concurrently
 * rather than after them"). Exposed separately from `runBootstrap` so route
 * guards can `await` just the REST half without needing a live WS in tests.
 */
import { applySystemUpdate, setShellState } from "./bootstrap/store.js";
import { runBootstrap, type BootstrapDeps } from "./bootstrap/bootstrap.js";
import { SystemSocket } from "./bootstrap/systemSocket.js";

export interface StartShellOptions extends BootstrapDeps {
  readonly wsUrl: string;
  readonly createSocket?: ConstructorParameters<typeof SystemSocket>[0]["createSocket"];
}

let activeSocket: SystemSocket | null = null;

/** Starts the bootstrap fetch and the `system` socket. Returns a `stop()`
 * to tear down the socket (used by tests and by logout). */
export function startShell(options: StartShellOptions): { stop(): void; ready: Promise<void> } {
  activeSocket?.stop();

  const socket = new SystemSocket({
    url: options.wsUrl,
    createSocket: options.createSocket,
    callbacks: {
      onSystemUpdate: (update) => applySystemUpdate(update),
      onConnectionChange: (connection) => setShellState({ connection }),
    },
  });
  activeSocket = socket;
  socket.connect();

  const ready = runBootstrap(options);

  return {
    ready,
    stop: () => {
      socket.stop();
      if (activeSocket === socket) activeSocket = null;
    },
  };
}
