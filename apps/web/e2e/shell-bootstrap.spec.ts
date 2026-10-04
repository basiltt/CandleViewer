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
  // R-100 `/terminal` redirects to the last-used layout (`12-sitemap.md` R-100).
  await expect(page).toHaveURL(/\/terminal\/last$/);
  expect(calls).toEqual(["me"]);
});

test("unauthenticated (/me 401) is redirected to /login", async ({ page }) => {
  await page.route("**/api/v1/me", (r) => r.fulfill({ status: 401, body: "{}" }));
  await page.route("**/api/v1/me/**", (r) => r.fulfill({ status: 401, body: "{}" }));
  await page.goto("/terminal");
  await expect(page).toHaveURL(/\/login/);
});

// E47-S06: theme switch + chart colour mode reach the document root that every
// surface (incl. the canvas theme object) keys off, after a real bootstrap.
test("stored theme and chart colour mode are applied to the root", async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem(
      "cv.chartColorMode",
      JSON.stringify({ palette: "cvd-safe", convention: "inverted" }),
    ),
  );
  await page.route("**/api/v1/me", (r) =>
    r.fulfill(
      json({
        role: "owner",
        permissions: [],
        session: { environment: "demo", elevated_until: null },
      }),
    ),
  );
  await page.route("**/api/v1/me/preferences", (r) =>
    r.fulfill(json({ appearance: { theme: "light" } })),
  );
  await page.route("**/api/v1/me/keymap", (r) => r.fulfill(json({ bindings: [] })));
  await page.goto("/terminal");
  const root = page.locator("html");
  await expect(root).toHaveAttribute("data-theme", "light");
  await expect(root).toHaveAttribute("data-palette", "cvd-safe");
  await expect(root).toHaveAttribute("data-convention", "inverted");
});
