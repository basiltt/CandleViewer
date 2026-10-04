import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("../src/lib/telemetry/aggregator", () => ({
  startTelemetry: () => ({ aggregator: {}, stop: vi.fn() }),
}));
const { App } = await import("../src/App");

describe("E49-S07 SCR-013 reachability via the real App", () => {
  it("Ctrl+/ opens the cheatsheet overlay mounted by App", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "/", ctrlKey: true });
    expect(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
  });
});
