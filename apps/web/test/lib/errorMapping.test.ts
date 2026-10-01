import { describe, expect, it } from "vitest";
import { WS_ERROR_CODES } from "@candleviewer/protocol";
import { classifyError } from "../../src/lib/ws/errorMapping";

describe("classifyError (23-ws-protocol.md 10.3)", () => {
  it("fatal codes get a modal", () => {
    for (const c of ["auth_failed", "forbidden", "user_disabled"]) {
      expect(classifyError(c)).toMatchObject({ uiClass: "fatal", modal: true });
    }
  });
  it("transient codes are inline, never a modal", () => {
    for (const c of ["degraded_data", "exchange_unavailable", "token_expired"]) {
      expect(classifyError(c)).toMatchObject({
        uiClass: "transient",
        modal: false,
        inlineBadge: true,
      });
    }
  });
  it("client bugs log and toast", () => {
    expect(classifyError("invalid_options")).toMatchObject({
      consoleError: true,
      toast: "reportBug",
    });
  });
  it("capacity codes advise fewer panes and reduce throttles", () => {
    expect(classifyError("slow_consumer")).toMatchObject({
      toast: "fewerPanes",
      autoReduceThrottle: true,
    });
  });
  it("unclassified or unknown codes are never silently swallowed", () => {
    expect(classifyError("not_a_code").consoleError).toBe(true);
    expect(classifyError("unknown_topic").uiClass).toBe("clientBug");
  });
  it("metadata drives retryable", () => {
    expect(classifyError("degraded_data").retryable).toBe(true);
  });
  it("every WS code resolves to a treatment", () => {
    for (const c of WS_ERROR_CODES) expect(classifyError(c).uiClass).toBeTruthy();
  });
});
