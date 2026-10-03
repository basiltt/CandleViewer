import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// E09-Q04: axe-core over all twelve E09 audit screens (WCAG 2.2 AA tags).
// Network is stubbed at the transport layer; no live calls. Screens whose real UI has not
// shipped yet render the shell placeholder; they are still scanned so the gate is in place
// the moment the screen lands (see docs/qa/a11y/e09-auth-a11y-audit.md).
test.describe.configure({ timeout: 90_000 });

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

export const E09_SCREENS: ReadonlyArray<{ scr: string; path: string }> = [
  { scr: "SCR-001", path: "/login" },
  { scr: "SCR-002", path: "/login/2fa" },
  { scr: "SCR-003", path: "/login/2fa/enroll" },
  { scr: "SCR-004", path: "/login/change-password" },
  { scr: "SCR-005", path: "/locked" },
  { scr: "SCR-006", path: "/admin/users/new" },
  { scr: "SCR-017", path: "/invite/tok-a11y-0123456789" },
  { scr: "SCR-019", path: "/terminal/last" },
  { scr: "SCR-111", path: "/settings/profile" },
  { scr: "SCR-112", path: "/settings/profile" },
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

for (const { scr, path } of E09_SCREENS) {
  test(`${scr} ${path}: no serious/critical axe violations`, async ({ page }) => {
    await stub(page);
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const res = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
      .analyze();
    const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
}
