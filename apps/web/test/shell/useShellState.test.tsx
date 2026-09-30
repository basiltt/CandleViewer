import { beforeEach, describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { useShellState } from "../../src/shell/useShellState.js";
import { resetShellState, setShellState } from "../../src/shell/bootstrap/store.js";

function Probe(): JSX.Element {
  const state = useShellState();
  return <div data-testid="env">{state.environment}</div>;
}

describe("useShellState", () => {
  beforeEach(() => {
    resetShellState();
  });

  it("renders the current shell state snapshot", () => {
    render(<Probe />);
    expect(screen.getByTestId("env").textContent).toBe("unknown");
  });

  it("re-renders when the store changes", () => {
    render(<Probe />);
    act(() => {
      setShellState({ environment: "live" });
    });
    expect(screen.getByTestId("env").textContent).toBe("live");
  });
});
