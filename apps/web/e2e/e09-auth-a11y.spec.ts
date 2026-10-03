import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// E09-Q04: axe-core over all twelve E09 audit screens (WCAG 2.2 AA tags).
// Network is stubbed at the transport layer; no live calls. Screens whose real UI has not
// shipped yet render the shell placeholder; they are still scanned so the gate is in place
// the moment the screen lands (see docs/qa/a11y/e09-auth-a11y-audit.md).
test.describe.configure({ timeout: 60_000 });

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

// `shipped: false` => the route still renders the StubRoute placeholder. Those are NOT counted as
// conformant: the test asserts the stub marker (so it fails loudly, forcing review, when the real
// screen lands) and is annotated as not-assessed instead of passing silently.
export const E09_SCREENS: ReadonlyArray<{ scr: string; path: string; shipped?: boolean }> = [
  { scr: "SCR-001", shipped: false, path: "/login" },
  { scr: "SCR-002", shipped: false, path: "/login/2fa" },
  { scr: "SCR-003", shipped: false, path: "/login/2fa/enroll" },
  { scr: "SCR-004", shipped: false, path: "/login/change-password" },
  { scr: "SCR-005", shipped: false, path: "/locked" },
  { scr: "SCR-006", path: "/admin/users/new" },
  { scr: "SCR-017", path: "/invite/tok-a11y-0123456789" },
  { scr: "SCR-019", path: "/terminal/last" },
  { scr: "SCR-111", shipped: false, path: "/settings/profile" },
  { scr: "SCR-112", shipped: false, path: "/settings/profile" },
  { scr: "SCR-123", path: "/admin/users/new" },
  { scr: "SCR-154", path: "/403" },
];

async function stub(page: Page): Promise<void> {
  const far = new Date(Date.now() + 3_600_000).toISOString();
  await page.route("**/api/v1/me", (r) =>
    r.fulfill(
      json({
        role: "owner",
        permissions: [],
        session: { environment: "demo", elevated_until: far },
      }),
    ),
  );
  await page.route("**/api/v1/me/preferences", (r) => r.fulfill(json({})));
  await page.route("**/api/v1/me/keymap", (r) => r.fulfill(json({ bindings: [] })));
  await page.route("**/api/v1/onboarding/checklist", (r) =>
    r.fulfill(json({ complete: true, dismissed: true, items: [] })),
  );
  await page.route("**/api/v1/invites/**", (r) =>
    r.fulfill(json({ display_name: "Ann", role: "viewer", expires_at: "x" })),
  );
}

test("E09 screen list covers all twelve SCR ids", () => {
  expect(new Set(E09_SCREENS.map((s) => s.scr)).size).toBe(12);
});

const SHIPPED = E09_SCREENS.filter((s) => s.shipped !== false);

for (const { scr, path, shipped } of E09_SCREENS) {
  test(`${scr} ${path}: axe serious/critical`, async ({ page }) => {
    await stub(page);
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    if (shipped === false) {
      test.info().annotations.push({ type: "not-assessed", description: "placeholder screen" });
      await expect(page.getByText("This screen has not shipped yet.")).toBeVisible();
      return;
    }
    await expect(page.getByText("This screen has not shipped yet.")).toHaveCount(0);
    const res = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
      .analyze();
    const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
}

for (const { scr, path } of SHIPPED) {
  test(`${scr}: reflow at 320px, no horizontal scroll (SC 1.4.10)`, async ({ page }) => {
    await stub(page);
    await page.setViewportSize({ width: 320, height: 640 });
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test(`${scr}: reduced motion leaves no running animations (SC 2.3.3)`, async ({ page }) => {
    await stub(page);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const running = await page.evaluate(
      () => document.getAnimations().filter((a) => a.playState === "running").length,
    );
    expect(running).toBe(0);
  });
}
