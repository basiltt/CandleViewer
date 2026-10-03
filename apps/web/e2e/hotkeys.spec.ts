import { test, expect } from "@playwright/test";

// E49-S07 e2e. SCR-113 (/settings/hotkeys) is behind the auth guard, which the shell does not
// bootstrap yet (E10-T04); its conflict/reserved/destructive/import guards run in
// test/keymap-host.test.tsx against the real component. Here: the globally reachable paths.
test("Ctrl+/ opens the cheatsheet with a Customise link", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("main")).toBeVisible();
  await page.keyboard.press("Control+/");
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Customise" })).toHaveAttribute(
    "href",
    "/settings/hotkeys",
  );
});

test("inert press of an unregistered destructive binding explains once, politely", async ({
  page,
}) => {
  await page.goto("/");
  for (let i = 0; i < 3; i++) await page.keyboard.press("Control+Shift+X");
  const host = page.getByTestId("toast-host");
  await expect(host).toHaveAttribute("role", "status");
  await expect(host.locator("p")).toHaveCount(1);
  await expect(host).toContainText("Cancel all working orders");
});
