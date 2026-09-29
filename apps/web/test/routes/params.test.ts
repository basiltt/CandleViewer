import { describe, expect, it } from "vitest";
import {
  validateSymbol,
  validateTimeframe,
  validatePaneFocus,
  validatePanel,
  validateAccount,
  validateGroupBy,
  validateShowClosed,
  validateIsoDateTime,
  validateSpeed,
  validateFromReplay,
  validateRuleMode,
  validateStandalone,
} from "../../src/routes/params";

describe("validateSymbol", () => {
  it("accepts a well-formed symbol", () => {
    expect(validateSymbol("BTCUSDT", "ETHUSDT")).toEqual({ value: "BTCUSDT", corrected: false });
  });

  it("falls back to the last symbol and explains why on an invalid symbol", () => {
    const result = validateSymbol("bad!", "ETHUSDT");
    expect(result.value).toBe("ETHUSDT");
    expect(result.corrected).toBe(true);
    expect(result.reason).toBeDefined();
  });

  it("falls back when missing", () => {
    expect(validateSymbol(null, "ETHUSDT").value).toBe("ETHUSDT");
  });
});

describe("validateTimeframe", () => {
  it("accepts every documented timeframe", () => {
    for (const tf of ["1", "15", "D", "W", "M"]) {
      expect(validateTimeframe(tf)).toEqual({ value: tf, corrected: false });
    }
  });

  it("defaults to 15 on an invalid value (§7 documented fallback)", () => {
    const result = validateTimeframe("99");
    expect(result.value).toBe("15");
    expect(result.corrected).toBe(true);
  });

  it("defaults to 15 when missing", () => {
    expect(validateTimeframe(undefined).value).toBe("15");
  });
});

describe("validatePaneFocus", () => {
  it("passes through a non-empty pane id", () => {
    expect(validatePaneFocus("pane-3")).toEqual({ value: "pane-3", corrected: false });
  });

  it("returns null when absent", () => {
    expect(validatePaneFocus(null)).toEqual({ value: null, corrected: false });
  });
});

describe("validatePanel", () => {
  it("accepts a known panel id", () => {
    expect(validatePanel("order-ticket").value).toBe("order-ticket");
  });

  it("ignores an unknown panel id", () => {
    const result = validatePanel("bogus");
    expect(result.value).toBeNull();
    expect(result.corrected).toBe(true);
  });
});

describe("validateAccount", () => {
  it("accepts a well-formed UUID", () => {
    const uuid = "123e4567-e89b-12d3-a456-426614174000";
    expect(validateAccount(uuid)).toEqual({ value: uuid, corrected: false });
  });

  it("rejects a malformed id", () => {
    const result = validateAccount("not-a-uuid");
    expect(result.value).toBeNull();
    expect(result.corrected).toBe(true);
  });
});

describe("validateGroupBy", () => {
  it("accepts each documented enum value", () => {
    for (const v of ["symbol", "account", "manager"]) {
      expect(validateGroupBy(v).value).toBe(v);
    }
  });

  it("falls back to symbol on an invalid value", () => {
    expect(validateGroupBy("bogus").value).toBe("symbol");
  });
});

describe("validateShowClosed", () => {
  it("parses true/false", () => {
    expect(validateShowClosed("true").value).toBe(true);
    expect(validateShowClosed("false").value).toBe(false);
  });

  it("defaults to false when absent or malformed", () => {
    expect(validateShowClosed(null).value).toBe(false);
    expect(validateShowClosed("yes").corrected).toBe(true);
  });
});

describe("validateIsoDateTime", () => {
  it("accepts a valid ISO datetime", () => {
    expect(validateIsoDateTime("2026-09-01T00:00:00Z").corrected).toBe(false);
  });

  it("rejects an invalid datetime", () => {
    const result = validateIsoDateTime("not-a-date");
    expect(result.value).toBeNull();
    expect(result.corrected).toBe(true);
  });
});

describe("validateSpeed", () => {
  it("passes a value within range unchanged", () => {
    expect(validateSpeed("4").value).toBe(4);
  });

  it("clamps below the minimum (0.5-100 §7)", () => {
    const result = validateSpeed("0.1");
    expect(result.value).toBe(0.5);
    expect(result.corrected).toBe(true);
  });

  it("clamps above the maximum", () => {
    const result = validateSpeed("500");
    expect(result.value).toBe(100);
    expect(result.corrected).toBe(true);
  });

  it("defaults to 1x when missing or NaN", () => {
    expect(validateSpeed("abc").value).toBe(1);
    expect(validateSpeed(null).value).toBe(1);
  });
});

describe("validateFromReplay", () => {
  it("passes through a non-empty session id", () => {
    expect(validateFromReplay("session-1").value).toBe("session-1");
  });
});

describe("validateRuleMode", () => {
  it("accepts form and graph", () => {
    expect(validateRuleMode("form").value).toBe("form");
    expect(validateRuleMode("graph").value).toBe("graph");
  });

  it("defaults to form on an invalid value", () => {
    expect(validateRuleMode("bogus").value).toBe("form");
  });
});

describe("validateStandalone", () => {
  it("treats 1 and true as true", () => {
    expect(validateStandalone("1").value).toBe(true);
    expect(validateStandalone("true").value).toBe(true);
  });

  it("defaults to false otherwise", () => {
    expect(validateStandalone(null).value).toBe(false);
    expect(validateStandalone("0").value).toBe(false);
  });
});
