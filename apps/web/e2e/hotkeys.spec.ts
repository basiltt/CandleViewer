import { test, expect } from "@playwright/test";

// E49-S07 regression guards per conflict class (run against the booted app; Electron
// shell-reserved keys are covered by reserved-keys.json platform entries).
test("reserved key press is not swallowed by the app (devtools key stays the platform's)", async ({
  page,
}) => {
  await page.goto("/");
  const prevented = await page.evaluate(
    () =>
      new Promise<boolean>((res) => {
        window.addEventListener("keydown", (e) => queueMicrotask(() => res(e.defaultPrevented)), {
          once: true,
        });
        window.dispatchEvent(
          new KeyboardEvent("keydown", {
            key: "I",
            ctrlKey: true,
            shiftKey: true,
            cancelable: true,
          }),
        );
      }),
  );
  expect(prevented).toBe(false);
});

test("inert press of a destructive binding shows one polite explanation and nothing executes", async ({
  page,
}) => {
  await page.goto("/");
  for (let i = 0; i < 3; i++) await page.keyboard.press("Control+Shift+X");
  const host = page.getByTestId("toast-host");
  await expect(host).toHaveAttribute("role", "status");
  await expect(host.locator("p")).toHaveCount(1);
  await expect(host).toContainText("Cancel all working orders");
});
