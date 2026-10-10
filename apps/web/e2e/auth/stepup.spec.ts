import { test, expect } from "@playwright/test";
import { assertNoClientSecrets, json, stubSession, watchForLeaks } from "../support/api";
import { OTP_SEED, totp } from "../support/totp";

// E09-Q02 (#293) stepup.spec. The browser clock is controlled with page.clock (no sleeps). The
// 5-minute server window (SR-025) is server-evaluated; the SPA's own guard window is exercised here
// and the server half is deferred to the test-only clock endpoint (see automation-status doc).
const T0 = new Date("2026-03-01T10:00:00Z");
const MIN = 60_000;

test("E09-TC-C04 stale step-up on a gated route shows the step-up dialog, not the page", async ({
  page,
}) => {
  await page.clock.install({ time: T0 });
  await stubSession(page, {
    role: "owner",
    elevatedUntil: () => new Date(T0.getTime() - 45 * MIN).toISOString(),
  });
  await page.goto("/admin/users");
  const dialog = page.getByRole("dialog", { name: "Confirm it's you" });
  await expect(dialog).toBeVisible();
  await expect(page.getByLabel("Authenticator code")).toBeVisible();
});

test("E09-TC-C05 step-up with a TOTP code succeeds and the grace window is shown", async ({
  page,
}) => {
  await page.clock.install({ time: T0 });
  const guard = watchForLeaks(page, ["step-up-marker-x"]);
  await stubSession(page, { role: "owner", elevatedUntil: () => null });
  let sent = "";
  await page.route("**/api/v1/auth/step-up", (r) => {
    sent = r.request().postData() ?? "";
    return r.fulfill(
      json({
        elevated_until: T0.toISOString(),
        step_up_expires_at: new Date(T0.getTime() + 5 * MIN).toISOString(),
      }),
    );
  });
  await page.goto("/admin/users");
  const code = totp(OTP_SEED, T0.getTime());
  await page.getByLabel("Password", { exact: true }).fill("e2e-step-up-pw");
  await page.getByLabel("Authenticator code").fill(code);
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText(/Grace window/u)).toContainText("Grace window: 5:00 remaining");
  expect(JSON.parse(sent)).toEqual({ code, password: "e2e-step-up-pw" });
  await expect(page.getByRole("button", { name: "Continue" })).toBeVisible();
  await assertNoClientSecrets(page, [code, "step-up-marker-x"]);
  await guard.flush();
});

test("E09-TC-C06 after the window the grace countdown reaches zero (fake clock)", async ({
  page,
}) => {
  await page.clock.install({ time: T0 });
  await stubSession(page, { role: "owner", elevatedUntil: () => null });
  await page.route("**/api/v1/auth/step-up", (r) =>
    r.fulfill(
      json({
        elevated_until: T0.toISOString(),
        step_up_expires_at: new Date(T0.getTime() + 5 * MIN).toISOString(),
      }),
    ),
  );
  await page.goto("/admin/users");
  await page.getByLabel("Password", { exact: true }).fill("e2e-step-up-pw");
  await page.getByLabel("Authenticator code").fill("123456");
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText(/Grace window/u)).toContainText("remaining");
  await page.clock.runFor(6 * MIN);
  await expect(page.getByText(/Grace window/u)).toHaveCount(0);
});

test("E09-TC-C05 rejected code keeps the gate closed with an accessible error", async ({
  page,
}) => {
  await page.clock.install({ time: T0 });
  await stubSession(page, { role: "owner", elevatedUntil: () => null });
  await page.route("**/api/v1/auth/step-up", (r) => r.fulfill(json({}, 401)));
  await page.goto("/admin/users");
  await page.getByLabel("Authenticator code").fill("000000");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toHaveText("That code did not work. Try again.");
  await expect(page.getByRole("dialog", { name: "Confirm it's you" })).toBeVisible();
});

test("E09-TC-C05 non-owner is denied (404) rather than offered step-up", async ({ page }) => {
  await page.clock.install({ time: T0 });
  await stubSession(page, { role: "manager" });
  await page.goto("/admin/users");
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
