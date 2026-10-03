import { ROUTE_MANIFEST } from "../../src/routes/manifest";

/**
 * Screen set for the accessibility collectors (E47-T02, 05-accessibility-standard.md s9).
 * PR set = routes that render without a session; the nightly full sweep
 * (A11Y_SWEEP=full) covers every manifest route with params filled in.
 */
export interface A11yScreen {
  readonly id: string;
  readonly path: string;
}

const PR_IDS = new Set(["R-001", "R-901", "R-902", "R-903"]);

export const FULL = process.env["A11Y_SWEEP"] === "full";

export const SCREENS: readonly A11yScreen[] = ROUTE_MANIFEST.filter(
  (e) => FULL || PR_IDS.has(e.id),
).map((e) => ({ id: e.id, path: e.path.replace(/:[A-Za-z]+/g, "x") }));

export const REPORT_DIR = process.env["A11Y_REPORT_DIR"] ?? "../../reports/a11y";
