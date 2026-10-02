import { describe, expect, it, vi } from "vitest";

const stop = vi.fn();
const startShell = vi.fn((o: { wsUrl: string }) => ({ stop, ready: Promise.resolve(), opts: o }));
const render = vi.fn();
vi.mock("../src/shell/startShell", () => ({ startShell }));
vi.mock("../src/App", () => ({ App: () => null }));
vi.mock("react-dom/client", () => ({ createRoot: () => ({ render }) }));

describe("main.tsx", () => {
  it("calls startShell and renders only after bootstrap resolves", async () => {
    document.body.innerHTML = '<div id="root"></div>';
    await import("../src/main");
    expect(startShell).toHaveBeenCalledTimes(1);
    expect(startShell.mock.calls[0]![0]).toMatchObject({
      wsUrl: expect.stringMatching(/^wss?:\/\/.+\/api\/v1\/ws$/),
    });
    await vi.waitFor(() => expect(render).toHaveBeenCalledTimes(1));
    expect(render).toHaveBeenCalledTimes(1);
  });
});
