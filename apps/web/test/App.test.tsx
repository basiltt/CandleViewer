import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { App } from "../src/App";

describe("App", () => {
  it("renders inside a main landmark after the root redirect", async () => {
    render(<App />);
    expect(await screen.findByRole("main")).toBeInTheDocument();
  });
});
