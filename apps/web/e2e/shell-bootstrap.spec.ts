import { test, expect } from "@playwright/test";

// E10-T04-B1 (#1725): the real app (main.tsx -> startShell) loads the session
// from /me, so an authenticated route renders instead of redirecting to /login.
// The API is stubbed at the network layer; the app code is not mocked.
const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

test("authenticated session reaches /terminal without redirect to /login", async ({ page }) => {
  const calls: string[] = [];
  await page.route("**/api/v1/me", (r) => {
    calls.push("me");
    return r.fulfill(
      json({
        role: "owner",
        permissions: [],
        session: { environment: "demo", elevated_until: null },
      }),
    );
  });
  await page.route("**/api/v1/me/preferences", (r) => r.fulfill(json({})));
  await page.route("**/api/v1/me/keymap", (r) => r.fulfill(json({ bindings: [] })));
  await page.goto("/terminal");
  await expect(page).toHaveURL(/\/terminal$/);
  expect(calls).toEqual(["me"]);
});

test("unauthenticated (/me 401) is redirected to /login", async ({ page }) => {
  await page.route("**/api/v1/me", (r) => r.fulfill({ status: 401, body: "{}" }));
  await page.route("**/api/v1/me/**", (r) => r.fulfill({ status: 401, body: "{}" }));
  await page.goto("/terminal");
  await expect(page).toHaveURL(/\/login/);
});
