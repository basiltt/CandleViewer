import { test, expect } from "@playwright/test";
import { json, stubSession } from "../support/api";

// E09-Q02 (#293) session.spec. SCR-005 (idle lock) and SCR-111/112 (sessions list, sign-out
// everywhere) are design-gated -> #1640 and are NOT built; those cases are deferred in
// qa/plans/e09-q02-automation-status.md. Covered here against shipped screens: the unauthenticated
// redirect, cookie-stripped/401 handling, and the bootstrap session read. @electron tagged.

test("E09-TC-C09 unauthenticated deep link redirects to /login preserving next @electron", async ({
  page,
}) => {
  await page.route("**/api/v1/me", (r) => r.fulfill(json({}, 401)));
  await page.goto("/positions");
  await expect(page).toHaveURL(/\/login\?next=%2Fpositions$/u);
  await expect(page.getByRole("heading", { name: "Sign in to CandleViewer" })).toBeVisible();
});

test("E09-TC-C01 authenticated bootstrap reads /me once and renders the shell @electron", async ({
  page,
}) => {
  let meCalls = 0;
  await stubSession(page, { role: "owner" });
  await page.route("**/api/v1/me", (r) => {
    meCalls += 1;
    return r.fulfill(
      json({
        role: "owner",
        permissions: [],
        session: { environment: "demo", elevated_until: null },
      }),
    );
  });
  await page.goto("/terminal/last");
  await expect(page).toHaveURL(/\/terminal\/last$/u);
  expect(meCalls).toBe(1);
});

test("E09-TC-C09 session cookie is never readable by page script (HttpOnly contract)", async ({
  page,
  context,
}) => {
  await context.addCookies([
    {
      name: "cv_session",
      value: "opaque-test-value",
      url: "http://127.0.0.1:4173",
      httpOnly: true,
      sameSite: "Strict",
    },
  ]);
  await stubSession(page, { role: "owner" });
  await page.goto("/terminal/last");
  expect(await page.evaluate(() => document.cookie)).not.toContain("cv_session");
  const [cookie] = await context.cookies();
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe("Strict");
});

test("E09-TC-C01 sign-in response body carries no token or secret (SR-012)", async ({ page }) => {
  const seen: string[] = [];
  await page.route("**/api/v1/auth/login", (r) => {
    const body = json({ status: "mfa_required", mfa_token: "ch-1", methods: ["totp"] });
    seen.push(body.body);
    return r.fulfill(body);
  });
  await page.goto("/login");
  await page.getByLabel("Username or email").fill("ann");
  await page.getByLabel("Password", { exact: true }).fill("pw-a1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Two-factor code" })).toBeVisible();
  expect(seen.join("")).not.toMatch(/session|password|recovery/iu);
  await expect(page.locator("body")).not.toContainText("pw-a1");
});
