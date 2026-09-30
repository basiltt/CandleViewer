import { beforeEach, describe, expect, it, vi } from "vitest";
import { startShell } from "../../src/shell/startShell.js";
import { getShellState, resetShellState } from "../../src/shell/bootstrap/store.js";

class FakeWebSocket extends EventTarget {
  static instances: FakeWebSocket[] = [];
  constructor(
    readonly url: string,
    readonly protocols: string[],
  ) {
    super();
    FakeWebSocket.instances.push(this);
  }
  send(): void {}
  close(): void {
    this.dispatchEvent(new Event("close"));
  }
  emitOpen(): void {
    this.dispatchEvent(new Event("open"));
  }
  emitMessage(data: string): void {
    this.dispatchEvent(new MessageEvent("message", { data }));
  }
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200 });
}

describe("startShell", () => {
  beforeEach(() => {
    resetShellState();
    FakeWebSocket.instances = [];
  });

  it("starts the WS connection and the REST bootstrap concurrently", () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}));
    const handle = startShell({
      wsUrl: "wss://localhost/api/v1/ws",
      fetchImpl,
      createSocket: (url, protocols) => new FakeWebSocket(url, protocols) as unknown as WebSocket,
    });
    expect(FakeWebSocket.instances.length).toBe(1);
    expect(fetchImpl).toHaveBeenCalled();
    handle.stop();
  });

  it("routes system frames into the shell store's systemByKind", () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}));
    const handle = startShell({
      wsUrl: "wss://localhost/api/v1/ws",
      fetchImpl,
      createSocket: (url, protocols) => new FakeWebSocket(url, protocols) as unknown as WebSocket,
    });
    const fake = FakeWebSocket.instances[0]!;
    fake.emitOpen();
    fake.emitMessage(
      JSON.stringify({
        t: "d",
        ch: "system",
        s: 1,
        ts: 1,
        e: "j",
        p: { kind: "health", health: "healthy" },
      }),
    );
    expect(getShellState().systemByKind.health).toEqual({ kind: "health", health: "healthy" });
    handle.stop();
  });

  it("stopping one shell tears down the previous socket before starting a new one", () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}));
    const first = startShell({
      wsUrl: "wss://localhost/api/v1/ws",
      fetchImpl,
      createSocket: (url, protocols) => new FakeWebSocket(url, protocols) as unknown as WebSocket,
    });
    const second = startShell({
      wsUrl: "wss://localhost/api/v1/ws",
      fetchImpl,
      createSocket: (url, protocols) => new FakeWebSocket(url, protocols) as unknown as WebSocket,
    });
    expect(FakeWebSocket.instances.length).toBe(2);
    first.stop();
    second.stop();
  });
});
