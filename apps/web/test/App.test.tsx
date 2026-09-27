import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { App } from "../src/App";

describe("App", () => {
  it("renders the placeholder route inside a main landmark", () => {
    render(<App />);
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "CandleViewer" })).toBeInTheDocument();
  });

  it("renders a focusable placeholder control reachable by keyboard", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: "Focusable placeholder control" });
    expect(button).toBeInTheDocument();
    expect(button.tabIndex).not.toBe(-1);
  });
});
