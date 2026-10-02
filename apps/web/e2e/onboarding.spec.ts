import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// E09-S06: first sign-in lands in the terminal and shows the SCR-019 card; axe clean.
const items = ["tailscale", "totp", "sub_account", "api_key", "profile_limits", "demo_session"].map(
  (key) => ({
    key,
    state: "pending",
    reason: null,
    unblock_at: null,
    action_route: "/settings/accounts",
  }),
);

test("SCR-019 card renders on first sign-in; axe clean with tour open", async ({ page }) => {
  await page.route("**/api/v1/onboarding/checklist", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ complete: false, dismissed: false, items }),
    }),
  );
  await page.goto("/terminal/last");
  await expect(page.getByRole("heading", { name: "Finish setting up" })).toBeVisible();
  await expect(page.getByRole("dialog")).toBeVisible();
  const res = await new AxeBuilder({ page }).analyze();
  expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
    [],
  );
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
