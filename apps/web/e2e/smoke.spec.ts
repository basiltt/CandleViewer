import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("app boots and the placeholder route renders", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("CandleViewer");
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("heading", { name: "CandleViewer" })).toBeVisible();
});

test("placeholder route has zero serious or critical axe violations", async ({ page }) => {
  await page.goto("/");
  const results = await new AxeBuilder({ page }).analyze();
  const seriousOrCritical = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(seriousOrCritical).toEqual([]);
});
