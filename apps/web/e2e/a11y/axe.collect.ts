import { mkdirSync, writeFileSync } from "node:fs";
import { test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { REPORT_DIR, SCREENS } from "./screens";

// Gate 1 collector: axe over every screen -> reports/a11y/axe.json
test("collect axe", async ({ page }) => {
  const screens: Record<string, { violations: unknown[] }> = {};
  for (const s of SCREENS) {
    await page.goto(s.path);
    await page.getByRole("main").first().waitFor();
    const r = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
      .analyze();
    screens[s.id] = { violations: r.violations };
  }
  mkdirSync(REPORT_DIR, { recursive: true });
  writeFileSync(`${REPORT_DIR}/axe.json`, JSON.stringify({ screens }, null, 2));
});
