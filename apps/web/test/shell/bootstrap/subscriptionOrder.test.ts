import { describe, expect, it } from "vitest";
import { orderSubscriptionsForRestore } from "../../../src/shell/bootstrap/subscriptionOrder.js";

describe("orderSubscriptionsForRestore", () => {
  it("orders private before focused before other", () => {
    const result = orderSubscriptionsForRestore([
      { topic: "book.BTCUSDT.200", priority: "other" },
      { topic: "positions", priority: "private" },
      { topic: "bars.BTCUSDT.time.60", priority: "focused" },
      { topic: "orders", priority: "private" },
    ]);
    expect(result.map((r) => r.topic)).toEqual([
      "positions",
      "orders",
      "bars.BTCUSDT.time.60",
      "book.BTCUSDT.200",
    ]);
  });

  it("preserves insertion order within a priority bucket", () => {
    const result = orderSubscriptionsForRestore([
      { topic: "a", priority: "other" },
      { topic: "b", priority: "other" },
    ]);
    expect(result.map((r) => r.topic)).toEqual(["a", "b"]);
  });

  it("returns an empty array for no requests", () => {
    expect(orderSubscriptionsForRestore([])).toEqual([]);
  });
});
