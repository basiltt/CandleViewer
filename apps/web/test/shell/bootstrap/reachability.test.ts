import { describe, expect, it } from "vitest";
import { ReachabilityTracker } from "../../../src/shell/bootstrap/reachability.js";

describe("ReachabilityTracker", () => {
  it("starts reachable with no cause", () => {
    const tracker = new ReachabilityTracker();
    expect(tracker.current).toEqual({ reachable: true, cause: null });
  });

  it("flips to unreachable on the first recorded failure", () => {
    const tracker = new ReachabilityTracker();
    tracker.recordFailure();
    expect(tracker.current.reachable).toBe(false);
  });

  it("classifies as offline when navigator.onLine is false", () => {
    const spy = Object.getOwnPropertyDescriptor(navigator, "onLine");
    Object.defineProperty(navigator, "onLine", { value: false, configurable: true });
    try {
      const tracker = new ReachabilityTracker();
      tracker.recordFailure();
      expect(tracker.current.cause).toBe("offline");
    } finally {
      if (spy) Object.defineProperty(navigator, "onLine", spy);
    }
  });

  it("classifies as tailnet_unreachable when navigator reports online but requests fail", () => {
    const spy = Object.getOwnPropertyDescriptor(navigator, "onLine");
    Object.defineProperty(navigator, "onLine", { value: true, configurable: true });
    try {
      const tracker = new ReachabilityTracker();
      tracker.recordFailure();
      expect(tracker.current.cause).toBe("tailnet_unreachable");
    } finally {
      if (spy) Object.defineProperty(navigator, "onLine", spy);
    }
  });

  it("recovers to reachable on success and notifies subscribers", () => {
    const tracker = new ReachabilityTracker();
    const seen: boolean[] = [];
    tracker.subscribe((state) => seen.push(state.reachable));
    tracker.recordFailure();
    tracker.recordSuccess();
    expect(seen).toEqual([false, true]);
  });

  it("does not notify subscribers when the state does not change", () => {
    const tracker = new ReachabilityTracker();
    let notifications = 0;
    tracker.subscribe(() => {
      notifications += 1;
    });
    tracker.recordSuccess();
    expect(notifications).toBe(0);
  });

  it("unsubscribe stops further notifications", () => {
    const tracker = new ReachabilityTracker();
    let notifications = 0;
    const unsubscribe = tracker.subscribe(() => {
      notifications += 1;
    });
    unsubscribe();
    tracker.recordFailure();
    expect(notifications).toBe(0);
  });
});
