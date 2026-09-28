import { test } from "@playwright/test";

// E03-T06: `@demo-rest-only` harness (01-sdlc-and-branching.md §9).
//
// Staging (demo) E2E for order-placement/order-management scenarios must
// exercise the REST order-entry path only and assert no WS order-entry
// frames were sent. In R0 there are no order specs yet — the ticket
// requires the harness to exist before R3 needs it, and to fail if the
// `@demo-rest-only` *tag itself* disappears from the suite configuration
// (rather than silently running zero specs forever).
//
// Real specs land alongside the first order-placement Story/Task (per
// `02-definition-of-ready-done.md`: "any Story/Task whose acceptance
// criteria include order placement must include or extend a
// `@demo-rest-only` spec"); this file only proves the tag resolves and
// carries at least one placeholder assertion so `--grep @demo-rest-only`
// never silently selects zero tests.

test("@demo-rest-only harness placeholder — order specs arrive in R3", () => {
  // Intentionally not a page-driven assertion: no order-entry UI exists
  // yet (R0). This exists solely so `e2e:staging`'s tag selection
  // (`--grep @demo-rest-only`) has at least one matching spec and the CI
  // job fails loudly if the tag is ever renamed/removed instead of
  // silently reporting "0 tests ran" as green.
});
