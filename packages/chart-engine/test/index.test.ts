import { describe, expect, it } from "vitest";
import { createEngine } from "../src/core/handle.js";
import { CHART_ENGINE_VERSION } from "../src/index.js";

describe("chart-engine public export surface", () => {
  it("exposes createEngine returning a disposable handle", () => {
    const handle = createEngine();
    expect(typeof handle.dispose).toBe("function");
    expect(() => handle.dispose()).not.toThrow();
  });

  it("exposes a version marker matching the package version", () => {
    expect(CHART_ENGINE_VERSION).toBe("0.1.0");
  });
});
