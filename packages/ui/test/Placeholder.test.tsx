import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Placeholder } from "../src/primitives/Placeholder.js";

describe("Placeholder", () => {
  it("renders the given label as text content", () => {
    const html = renderToStaticMarkup(<Placeholder label="hello" />);
    expect(html).toContain("hello");
  });
});
