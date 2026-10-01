import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

const stop = vi.fn();
const start = vi.fn(() => ({ aggregator: {}, stop }));
vi.mock("../src/lib/telemetry/aggregator", () => ({ startTelemetry: start }));

const { App } = await import("../src/App");

describe("App telemetry wiring (E04-T06)", () => {
  afterEach(() => {
    start.mockClear();
    stop.mockClear();
  });

  it("starts the telemetry aggregator on mount and tears it down on unmount", () => {
    const view = render(<App />);
    expect(start).toHaveBeenCalledTimes(1);
    expect(stop).not.toHaveBeenCalled();
    view.unmount();
    expect(stop).toHaveBeenCalledTimes(1);
  });
});
