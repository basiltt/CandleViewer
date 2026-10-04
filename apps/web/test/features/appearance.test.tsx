import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createEngine } from "@candleviewer/chart-engine";
import { AppearanceScreen, LEGEND_VIEWS } from "../../src/features/appearance/AppearanceScreen";
import { registerEngine } from "../../src/features/appearance/engineRegistry";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.removeAttribute("data-palette");
  document.documentElement.removeAttribute("data-convention");
});

const ok = (): Response => ({ ok: true, status: 200, json: async () => ({}) }) as Response;

describe("SCR-116 appearance screen", () => {
  it("palette choice persists via PATCH /me/preferences and updates the root", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok());
    vi.stubGlobal("fetch", fetchMock);
    render(<AppearanceScreen />);
    fireEvent.click(screen.getByRole("radio", { name: /colour-blind safe/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/me/preferences");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({
      appearance: { chart_palette: "cvd-safe", chart_convention: "standard" },
    });
    expect(document.documentElement.getAttribute("data-palette")).toBe("cvd-safe");
    await screen.findByText("Saved.");
  });

  it("reports a failed save without losing the local choice", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    render(<AppearanceScreen />);
    fireEvent.click(screen.getByRole("checkbox", { name: /invert/i }));
    await screen.findByText(/could not save/i);
    expect(document.documentElement.getAttribute("data-convention")).toBe("inverted");
  });

  it("change palette -> engine setTheme with CVD palette -> one texture re-upload", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok()));
    const upload = vi.fn();
    const engine = createEngine({ uploadPalette: upload });
    const unregister = registerEngine(engine);
    render(<AppearanceScreen />);
    fireEvent.click(screen.getByRole("radio", { name: /colour-blind safe/i }));
    await screen.findByText("Saved.");
    expect(engine.stats().paletteUploads).toBe(1);
    expect(upload).toHaveBeenCalledTimes(1);
    expect((upload.mock.calls[0]?.[0] as { palette: string }).palette).toBe("cvd-safe");
    unregister();
  });

  it("every affected view's legend reflects palette/convention switches", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok()));
    render(<AppearanceScreen />);
    const groups = LEGEND_VIEWS.map((v) =>
      screen.getByRole("group", { name: `${v} colour legend` }),
    );
    for (const g of groups) expect(within(g).getByText("Green = buy / bid / up")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /colour-blind safe/i }));
    for (const g of groups) expect(within(g).getByText("Blue = buy / bid / up")).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: /invert/i }));
    for (const g of groups) {
      expect(within(g).getByText("Orange = buy / bid / up")).toBeTruthy();
      expect(g.getAttribute("data-convention")).toBe("inverted");
      expect(within(g).getAllByTestId("legend-swatch")[0]?.getAttribute("style")).toContain(
        "--color-buy-default",
      );
    }
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Saved."));
  });

  it("compact density: token >=24px and every interactive element carries it", () => {
    const tokens = JSON.parse(
      readFileSync(
        resolve(import.meta.dirname, "../../../../packages/ui/tokens/primitives.tokens.json"),
        "utf-8",
      ),
    ) as Record<string, { $value: string }>;
    expect(Number(tokens["size.target.min"]?.$value)).toBeGreaterThanOrEqual(24);
    document.documentElement.setAttribute("data-density", "compact");
    render(<AppearanceScreen />);
    const controls = screen.getAllByRole("radio").concat(screen.getAllByRole("checkbox"));
    expect(controls.length).toBe(3);
    for (const el of controls) {
      for (const node of [el, el.closest("label") as HTMLElement]) {
        expect(node.style.minWidth).toBe("var(--size-target-min, 24px)");
        expect(node.style.minHeight).toBe("var(--size-target-min, 24px)");
      }
    }
    document.documentElement.removeAttribute("data-density");
  });
});
