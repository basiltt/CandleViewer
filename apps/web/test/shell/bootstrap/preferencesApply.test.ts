import { describe, expect, it } from "vitest";
import { applyAppearance } from "../../../src/shell/bootstrap/preferencesApply.js";

function makeRoot(): HTMLElement {
  return document.createElement("html");
}

describe("applyAppearance", () => {
  it("applies stored theme and density without needing a reload", () => {
    const root = makeRoot();
    applyAppearance({ theme: "light", density: "compact" }, root);
    expect(root.getAttribute("data-theme")).toBe("light");
    expect(root.getAttribute("data-density")).toBe("compact");
  });

  it("applies high-contrast and reduced-motion flags", () => {
    const root = makeRoot();
    applyAppearance({ high_contrast: true, reduce_motion: true }, root);
    expect(root.getAttribute("data-high-contrast")).toBe("true");
    expect(root.getAttribute("data-reduced-motion")).toBe("true");
  });

  it("sets the font-scale custom property", () => {
    const root = makeRoot();
    applyAppearance({ font_scale: 1.25 }, root);
    expect(root.style.getPropertyValue("--cv-font-scale")).toBe("1.25");
  });

  it("falls back to safe defaults when preferences failed to load", () => {
    const root = makeRoot();
    applyAppearance(undefined, root);
    expect(root.getAttribute("data-theme")).toBe("dark");
    expect(root.getAttribute("data-density")).toBe("comfortable");
    expect(root.getAttribute("data-reduced-motion")).toBe("false");
  });
});
