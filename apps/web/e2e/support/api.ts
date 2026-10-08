import type { Page, Route } from "@playwright/test";

// Network-layer stubs shared by the E09-Q02 specs (no live backend, C-13.5). App code is not mocked.
export const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => ({
  status,
  contentType: "application/json",
  headers,
  body: JSON.stringify(body),
});

export interface MeOptions {
  readonly role: "owner" | "manager" | "viewer";
  readonly elevatedUntil?: () => string | null;
}

/** Stub the session bootstrap calls the shell makes for an authenticated user. */
export async function stubSession(page: Page, opts: MeOptions): Promise<void> {
  await page.route("**/api/v1/me", (r: Route) =>
    r.fulfill(
      json({
        role: opts.role,
        permissions: [],
        session: { environment: "demo", elevated_until: opts.elevatedUntil?.() ?? null },
      }),
    ),
  );
  await page.route("**/api/v1/me/preferences", (r) => r.fulfill(json({})));
  await page.route("**/api/v1/me/keymap", (r) => r.fulfill(json({ bindings: [] })));
}

/** Fails the test if any response body the page saw contains a secret-looking value (SR-012). */
export function watchForLeaks(page: Page, forbidden: readonly string[]): () => string[] {
  const leaks: string[] = [];
  page.on("response", (res) => {
    void res
      .text()
      .then((t) => {
        for (const f of forbidden)
          if (t.includes(f)) leaks.push(`${res.url()} leaked ${f.length}-char value`);
      })
      .catch(() => undefined);
  });
  return () => leaks;
}
