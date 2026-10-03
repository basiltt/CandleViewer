import { mkdirSync, writeFileSync } from "node:fs";
import { test } from "@playwright/test";
import { REPORT_DIR, SCREENS } from "./screens";

// Gate 6 collector: ARIA snapshot (role/name/landmark/heading tree) per screen
// as text -> reports/a11y/trees/<id>.txt. Committed baselines live in
// tools/a11y/tree-snapshots/ (refresh by copying the captured file in the PR).
test("collect a11y trees", async ({ page }) => {
  mkdirSync(`${REPORT_DIR}/trees`, { recursive: true });
  for (const s of SCREENS) {
    await page.goto(s.path);
    await page.getByRole("main").first().waitFor();
    const tree = await page.locator("body").ariaSnapshot();
    writeFileSync(`${REPORT_DIR}/trees/${s.id}.txt`, `${tree}\n`);
  }
});
