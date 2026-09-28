import { describe, expect, it } from "vitest";
import { checkRegressions } from "../../../scripts/check-bundle-size-regression.mjs";

describe("checkRegressions", () => {
  it("passes when size is unchanged", () => {
    expect(
      checkRegressions({ "dist/assets/*.js": 1000 }, [{ name: "dist/assets/*.js", size: 1000 }]),
    ).toEqual([]);
  });

  it("passes on growth within the 5% budget", () => {
    const violations = checkRegressions({ "dist/assets/*.js": 1000 }, [
      { name: "dist/assets/*.js", size: 1049 },
    ]);
    expect(violations).toEqual([]);
  });

  it("fails on growth beyond the 5% budget", () => {
    const violations = checkRegressions({ "dist/assets/*.js": 1000 }, [
      { name: "dist/assets/*.js", size: 1060 },
    ]);
    expect(violations).toHaveLength(1);
    expect(violations[0]).toMatch(/\+5\.9%|\+6\.0%/);
  });

  it("ignores a new entry with no baseline yet", () => {
    expect(checkRegressions({}, [{ name: "dist/assets/new.js", size: 5000 }])).toEqual([]);
  });

  it("passes on a shrink", () => {
    expect(
      checkRegressions({ "dist/assets/*.js": 1000 }, [{ name: "dist/assets/*.js", size: 500 }]),
    ).toEqual([]);
  });
});
