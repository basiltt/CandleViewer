import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("app boots and the placeholder route renders", async ({ page }) => {
  // E10-T01: an unauthenticated visit to "/" now redirects to the R-001
  // `/login` stub (12-sitemap.md §8) instead of rendering a route directly
  // at "/"; the app shell still boots with a `<main>` landmark and a
  // heading, which is what this smoke test guards.
  await page.goto("/");
  await expect(page).toHaveTitle("CandleViewer");
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("heading")).toBeVisible();
});

test("placeholder route has zero serious or critical axe violations", async ({ page }) => {
  await page.goto("/");
  const results = await new AxeBuilder({ page }).analyze();
  const seriousOrCritical = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(seriousOrCritical).toEqual([]);
});
