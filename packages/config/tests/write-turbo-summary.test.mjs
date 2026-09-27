import { describe, expect, it } from "vitest";
import { renderSummary } from "../../../tools/ci/write-turbo-summary.mjs";

describe("renderSummary", () => {
  it("renders a markdown table with cache status and duration", () => {
    const summary = renderSummary("lint", {
      tasks: [
        {
          package: "@candleviewer/ui",
          task: "lint",
          cache: { status: "HIT" },
          execution: { exitCode: 0, startTime: 1000, endTime: 1500 },
        },
        {
          package: "@candleviewer/web",
          task: "lint",
          cache: { status: "MISS" },
          execution: { exitCode: 0, startTime: 2000, endTime: 3200 },
        },
      ],
    });

    expect(summary).toContain("JS lane: `lint`");
    expect(summary).toContain("@candleviewer/ui");
    expect(summary).toContain("HIT");
    expect(summary).toContain("500 ms");
    expect(summary).toContain("@candleviewer/web");
    expect(summary).toContain("MISS");
    expect(summary).toContain("1200 ms");
  });

  it("falls back gracefully when there are no tasks", () => {
    const summary = renderSummary("build", { tasks: [] });
    expect(summary).toContain("no task summary available");
  });
});
