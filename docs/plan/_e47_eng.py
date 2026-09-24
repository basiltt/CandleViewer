# -*- coding: utf-8 -*-
"""E47 engineering tickets: K01, T01-T08, S01-S06."""

SCREEN_BANDS = """The 149 SCR-* screens are audited in these bands (`docs/plan/14-screens-catalogue.md`):
auth/onboarding SCR-001..019, workspace/layout SCR-020..029, chart SCR-030..049,
DOM/heatmap/tape SCR-050..059, trading SCR-060..079, rules SCR-080..089,
watchlist/alerts/journal/replay SCR-090..104, settings SCR-110..119,
admin SCR-120..149, global states SCR-150..159."""


def build_eng(t, REFS_COMMON):

    # ---------------------------------------------------------------- K01
    t("E47-K01", "Spike",
      "Spike: prove the a11y audit harness scales to 149 screens in CI",
      ["type/spike", "a11y", "qa", "area/design-system", "priority/p1"],
      "web", "Sprint 22", "P1 High", "Development", "R5 Scope",
      2, "E47", [],
      """## Context
E47's whole strategy (`docs/plan/05-accessibility-standard.md` section 9) is "mechanise the audit first, remediate second". That only works if a single CI job can drive **every** screen in `docs/plan/14-screens-catalogue.md` - 149 SCR-* entries - through axe-core, Lighthouse and an accessibility-tree snapshot inside a sane wall-clock budget. Many of those screens are not reachable by a plain URL: they are panels inside `/w/:workspaceId` (SCR-030, SCR-050, SCR-060), transient states (SCR-150..159), RBAC-gated admin screens (SCR-120..149), or overlays (SCR-025 command palette, the `Ctrl+/` hotkey overlay).

Before we commit E47-T01's 5 points we need to know: can we reach each screen deterministically, how long does a full sweep take, and does the existing Playwright + seeded-fixture infrastructure from `docs/plan/03-testing-strategy.md` cover it. Getting this wrong turns the S23 audit sprint into an infrastructure sprint.

Timebox: 3 days, one frontend engineer plus the frontend a11y champion.

## Scope / Deliverables
- A **screen-reachability inventory**: a checked-in `frontend/tests/a11y/screens.ts` manifest mapping every SCR-* id to `{route, rbacRole, setupFn, panelFocus, kind: page|panel|overlay|state}`. Screens that cannot currently be reached deterministically are listed explicitly with the blocker.
- A throwaway prototype harness that drives a representative sample of **12 screens**, one per band above: SCR-001 (login), SCR-020 (workspace), SCR-030 (chart panel), SCR-050 (heatmap+ladder), SCR-060 (order ticket), SCR-081 (node-graph editor), SCR-093 (alerts), SCR-100 (journal), SCR-116 (appearance), SCR-117 (accessibility settings), SCR-121 (admin users), SCR-152 (a global error/degraded state).
- Measured numbers: per-screen wall-clock for axe, for Lighthouse, for `accessibility.snapshot()`; extrapolated full-sweep time on the CI runner; flake rate over 5 consecutive runs.
- A recommendation on sharding (how many CI shards, which gate runs per-PR vs nightly), on the Lighthouse subset (section 9.2 only mandates >= 95 on *top-level* screens, not all 149), and on the fixture/seed strategy for admin and transient states.
- A short written spike report at `docs/a11y/spike-harness.md` with the decision and the rejected options.

## Out of scope
- Building the production harness (that is E47-T01) or fixing any finding it reports.
- Screen-reader automation - manual SR passes stay manual (E47-Q02).
- Deciding CVD palette validation approach (E47-T02 owns that).

## Acceptance criteria
```gherkin
Scenario: Every screen has a known reachability status
  Given the checked-in screens manifest
  When it is diffed against the SCR-* ids in docs/plan/14-screens-catalogue.md
  Then all 149 ids are present
  And each is either marked reachable with a setup function, or marked blocked
    with a named blocker and a proposed fix

Scenario: Full-sweep cost is measured, not guessed
  Given the 12-screen prototype run on the CI runner
  Then per-screen timings for axe, Lighthouse and tree-snapshot are recorded
  And an extrapolated full-sweep duration and a shard count recommendation are
    written into docs/a11y/spike-harness.md

Scenario: Flake is quantified before we gate on it
  Given the prototype is run 5 times against an unchanged build
  Then the run-to-run variation in axe findings is reported
  And any non-deterministic screen is named with its cause (animation, live data,
    clock) and a proposed stabilisation (freeze clock, seeded fixture feed)

Scenario: Failure path - a screen cannot be reached
  Given SCR-152 (a degraded/error state) cannot be driven deterministically
  When the spike concludes
  Then it is recorded as blocked with a proposed test hook rather than silently
    dropped from the audit scope
```

## Technical notes / design
Use the existing Playwright setup from `docs/plan/03-testing-strategy.md` against the built web bundle in headless Chromium (per `05-accessibility-standard.md` section 8.1 row 3 - Chromium is the CI feedback target; Electron stays manual). Seed data comes from the recorded-fixture harness already used by integration tests so the chart, footprint and ladder surfaces have real bars/levels rather than empty states - an empty canvas would produce a falsely clean audit.

Manifest shape:
```ts
export type ScreenEntry = {
  id: `SCR-${string}`;
  kind: 'page' | 'panel' | 'overlay' | 'state';
  route: string;                 // e.g. '/w/:workspaceId?focus=chart-1'
  rbacRole: 'owner' | 'manager' | 'viewer';
  setup?: (page: Page) => Promise<void>;  // seed, open panel, force state
  lighthouse: boolean;           // true only for the section 9.2 top-level set
};
```
Known-hard cases to answer explicitly: transient global states SCR-150..159 (need a test-only state-forcing hook), RBAC screens (need three seeded sessions), the node-graph editor SCR-081 (canvas + custom focus model), and overlays that trap focus.

## Test plan
Spike output is a report plus a prototype, not shipped code. The prototype must run green 5 times to produce its flake number. No coverage target; the manifest itself is later covered by E47-T01's completeness test.

## Security notes
Seeded fixtures must contain synthetic accounts and symbols only - never real Bybit API keys, account ids or live positions (`docs/plan/04-security-program.md`). The spike report is checked into the repo and must not embed screenshots of real data.

## Accessibility notes
N/A as a product surface - this ticket is a11y infrastructure. It produces no UI.

## Performance notes
The sweep budget is the deliverable: target a per-PR gate under 10 minutes wall-clock after sharding; anything slower moves to the nightly job. This constraint is what E47-T01 will be designed against.

## Observability
None in product. The prototype emits timing JSON per screen so the recommendation is reproducible.

## Definition of Done
- [ ] `docs/a11y/spike-harness.md` written with decision, numbers and rejected options.
- [ ] `frontend/tests/a11y/screens.ts` manifest covering all 149 ids merged.
- [ ] Prototype run 5x with flake numbers recorded.
- [ ] Reviewed by the frontend a11y champion and the QA/SDET lead.
- [ ] E47-T01 re-estimated (or confirmed) in light of the findings.

## Dependencies
Needs a deployable R4 build to drive. No blocked_by within E47 - this is the first ticket to start.

## Branch
`spike/e47-audit-harness` - prototype code may be discarded; the manifest and report are kept. PR size: manifest + report, ~300 LOC.

## References
""" + REFS_COMMON)

    # ---------------------------------------------------------------- T01
    t("E47-T01", "Task",
      "Build the automated accessibility audit harness over all 149 screens",
      ["type/chore", "a11y", "qa", "area/design-system", "priority/p0"],
      "web", "Sprint 23", "P0 Critical", "Development", "R5 Scope",
      5, "E47", ["E47-K01"],
      """## Context
This is the engine of E47. `docs/plan/05-accessibility-standard.md` section 9 mandates four automatable gates - axe-core (9.1), Lighthouse Accessibility >= 95 on top-level screens (9.2), keyboard-only E2E (9.4) and accessibility-tree snapshots (9.6). E47-T01 builds the harness and the **findings register** that the six remediation stories consume; E47-T03, E47-T04 and E47-T05 plug their specialised checks into it; E47-T06 later promotes it to a required check.

The deliberate sequencing (epic body, phase 1) is: generate the complete findings register *mechanically* in S23 before anyone starts fixing, so remediation is scoped from evidence rather than from opinion, and so no architectural non-conformance is discovered in S25 with no time to fix.

## Scope / Deliverables
- `frontend/tests/a11y/harness/` - a Playwright-driven sweep that, for each entry in the `screens.ts` manifest from E47-K01, navigates/sets up the screen and runs: `@axe-core/playwright` (WCAG 2.2 A + AA rule sets, plus `best-practice` recorded but not gating), `page.accessibility.snapshot()`, and Lighthouse for manifest entries flagged `lighthouse: true`.
- The section 9.2 tracked top-level screen set, pinned explicitly: SCR-020 (workspace), SCR-030 (chart panel), SCR-050 (heatmap + DOM ladder), SCR-060 (order ticket), SCR-063 (positions), SCR-080 (rules list), SCR-093 (alerts), SCR-100 (journal), SCR-110 (settings home), SCR-117 (accessibility settings), SCR-121 (admin users).
- **Findings register** at `docs/a11y/findings.csv`, columns `screen,component,wcag_sc,level,severity,source,owner_ticket,status,notes` where `status` is one of `open|in_progress|fixed|accepted|wont_fix`; the harness writes `open` rows and never overwrites human-set `owner_ticket`/`status` (merge-on-key, key = `screen+wcag_sc+component`).
- A triage helper `scripts/a11y/triage.py` that maps each open finding to its owning remediation story by screen band: chart SCR-030..049 to E47-S01; SCR-050..059 to E47-S02; SCR-080..089 to E47-S03; theme/palette findings to E47-S04; SCR-001..029, SCR-090..104, SCR-110..149, SCR-150..159 to E47-S05; SCR-060..079 and any confirm-gate finding to E47-S06.
- A completeness test asserting the manifest covers every SCR-* id parsed out of `docs/plan/14-screens-catalogue.md` - so a new screen cannot be added without being audited.
- CI wiring as a **non-blocking** job first (blocking comes in E47-T06), sharded per the K01 recommendation, publishing axe JSON, Lighthouse JSON and tree snapshots as retained artifacts.

## Out of scope
- Fixing any finding (that is E47-S01..S06).
- Making the gate merge-blocking (E47-T06).
- Contrast/CVD palette checks (E47-T02), motion/flash (E47-T04), keyboard task script (E47-T03) - they are separate tickets that register findings into the same CSV.
- Manual screen-reader passes (E47-Q02).

## Acceptance criteria
```gherkin
Scenario: The sweep covers every catalogued screen
  Given the harness completes a full run
  Then it reports a result for all 149 SCR-* ids
  And the completeness test fails the build if any catalogued id has no manifest
    entry

Scenario: Findings are registered, deduplicated and routed
  Given a serious axe violation on SCR-050
  When the sweep runs twice
  Then docs/a11y/findings.csv contains exactly one row for that
    screen+wcag_sc+component key
  And triage.py assigns owner_ticket E47-S02 to it

Scenario: Human triage decisions survive a re-run
  Given a finding whose status a human set to "accepted" with a note
  When the harness runs again and still detects it
  Then the status stays "accepted" and the note is preserved
  And the row is flagged "still-present" rather than reset to "open"

Scenario: Lighthouse is scored on the tracked set
  Given the 11 tracked top-level screens
  When the sweep runs
  Then each has a recorded Accessibility score
  And any score below 95 produces a finding row with level AA and severity serious

Scenario: Failure path - a screen fails to load
  Given SCR-121 cannot be reached because its seed session expired
  When the sweep runs
  Then the run fails loudly with that screen named
  And it is NOT silently recorded as "no violations found"
```

## Technical notes / design
Sweep skeleton:
```ts
for (const s of screens) {
  const page = await ctxFor(s.rbacRole).newPage();
  await gotoAndSetup(page, s);
  await freezeClockAndFeed(page);              // determinism, per K01 findings
  const axe = await new AxeBuilder({ page })
      .withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa'])
      .analyze();
  const tree = await page.accessibility.snapshot();
  record(s.id, axe, tree);
  if (s.lighthouse) record(s.id, await lighthouseA11y(page));
}
```
Determinism is the hard part and comes straight out of K01: freeze the clock, drive the market feed from a recorded fixture at a fixed offset, and disable animations for the axe pass only (motion is audited separately in E47-T04) so transient opacity states do not produce phantom contrast findings.

Canvas screens need the DOM mirror materialised before the snapshot: the harness focuses the canvas (`Tab` into it), which is what makes the `26-chart-engine-design.md` section 12 mirror populate. A canvas screen audited without focusing it would report an empty region and a false pass - the harness asserts the mirror has >= 1 mirrored unit on every canvas screen before running axe.

Severity mapping: axe `critical`/`serious` -> severity `serious`; `moderate`/`minor` -> `minor`. Level is taken from the mapped WCAG success criterion, not from axe's impact.

## Test plan
- Unit: findings-CSV merge logic (new row, duplicate row, human-edited row, resolved-then-regressed row); triage routing table (one case per band); screen-manifest completeness parser against a fixture catalogue.
- Integration: run the sweep against a build with a deliberately injected violation (a button with no accessible name on SCR-110) and assert the row appears with the right owner_ticket.
- Contract: the CSV schema is asserted by a test so downstream dashboards (E47-T06) do not break silently.
- Flake: 3 consecutive runs on an unchanged build must produce byte-identical open-finding sets.
- Coverage target: >= 80% lines on the harness' own non-Playwright logic (merge, triage, parse), per the frontend bar in `docs/plan/03-testing-strategy.md`.

## Security notes
The harness runs with three seeded RBAC sessions. Its fixtures and artifacts must contain no real keys, account ids or live positions (`docs/plan/04-security-program.md`). Retained CI artifacts include accessibility-tree snapshots which contain on-screen values - they inherit the same data classification as the screens themselves and are stored in the normal private CI artifact store, not published publicly. Explicitly assert that a Viewer-role sweep never produces a tree snapshot containing owner-only fields; this is the automated half of E47-X01's RBAC-leak threat.

## Accessibility notes
N/A as a product surface. The harness is the instrument, not a screen.

## Performance notes
Per-PR shard budget <= 10 min wall-clock (K01 recommendation); full nightly sweep <= 45 min. The harness must not itself change product behaviour - the animation-disable flag used for the axe pass is a test-only override and must not ship in the production bundle (asserted by a bundle test).

## Observability
- CI artifacts per run: `axe/*.json`, `lighthouse/*.json`, `tree/*.json`, plus `findings.csv` diff.
- Counter `a11y_findings_open{level,severity}` emitted to the dashboard consumed by E47-T06.

## Definition of Done
- [ ] Harness merged and running nightly and per-PR (non-blocking).
- [ ] `docs/a11y/findings.csv` generated with the complete S23 baseline register.
- [ ] Every open finding routed to one of E47-S01..S06 by triage.py.
- [ ] Unit + integration tests green; coverage >= 80% on harness logic.
- [ ] 3-run determinism check passes.
- [ ] Reviewed by the Accessibility role and the QA/SDET lead; docs updated in `docs/a11y/README.md`.

## Dependencies
- **E47-K01** supplies the screen manifest, reachability fixes and shard/flake strategy.
- Relies on the chart-engine DOM mirror API (`26-chart-engine-design.md` section 12, delivered by E11) and on the seeded-fixture feed from the integration-test harness.

## Branch
`feat/e47-audit-harness`. PR size guidance: split into (1) manifest + sweep runner, (2) findings register + triage, (3) CI wiring - each <= 400 LOC.

## References
""" + REFS_COMMON)

    # ---------------------------------------------------------------- T02
    t("E47-T02", "Task",
      "Automate the contrast and CVD palette matrix across all six themes",
      ["type/chore", "a11y", "area/design-system", "priority/p0"],
      "web", "Sprint 23", "P0 Critical", "Development", "R8 Browser/GPU compat",
      3, "E47", [],
      """## Context
`docs/plan/05-accessibility-standard.md` section 4 makes colour-independence non-negotiable and section 9.3 requires a token-level contrast linter. E05 shipped a linter for *text* token pairs. What has never been verified is the full matrix: six themes (dark, light, high-contrast, and the CVD-safe deuteranopia / protanopia / tritanopia palettes offered on SCR-116) times every **data-ink** encoding in the order-flow surfaces, which are not plain text pairs and therefore escape the existing linter.

US-SET-005 states it directly: "an automated check asserts no view depends on hue alone". US-SET-004 states "contrast verified automatically in CI for both themes and all palettes". This ticket builds that check and produces the colour half of the findings register that E47-S04 remediates.

## Scope / Deliverables
- `packages/design-tokens/scripts/contrast-matrix.ts` extended from the existing token linter to evaluate, per theme, every pair in a declared **encoding manifest** covering: footprint delta and imbalance shading (CMP-109 FootprintCell), heatmap bid/ask gradient (CMP-111 HeatmapCell, CMP-113 HeatmapLegend), CVD sign, profile bars (CMP-110 ProfileBar), big-trade bubbles (CMP-112 BigTradeBubble), P&L (CMP-116 PnLBadge), order status (CMP-115 OrderRow), side (CMP-102 SideToggle), risk-cap severity (CMP-138 RiskCapMeter), LIVE/DEMO badge, focus ring, and the DOM-ladder own-order marker (CMP-108 DomLadderRow).
- Thresholds enforced: 4.5:1 for normal text, 3:1 for large text and non-text UI components / focus rings (SC 1.4.11), and the section 1 AAA stretch of 7:1 for buy/sell primary actions and the LIVE/DEMO badge - the 7:1 check is reported as a warning, the AA checks as failures.
- A **hue-independence assertion**: each entry in the encoding manifest must declare its non-colour channel (`glyph`, `sign`, `text`, `pattern`, `position`); an entry declaring `none` fails the build. This is the machine-checkable form of the section 4 triad rule.
- A **CVD simulation pass**: apply deuteranopia/protanopia/tritanopia transforms to the dark and light palettes and assert that any two encodings which must remain distinguishable (bid vs ask, buy vs sell, profit vs loss, working vs rejected) keep >= 3:1 contrast *against each other* after simulation - catching "both become the same brown" failures.
- A `forced-colors: active` (Windows High Contrast) case: assert the token layer falls back to system colours for chrome while the canvas keeps its token-driven palette (never system-colour-dependent), per the epic's R8 mitigation.
- Machine-readable output `docs/a11y/contrast-matrix.json` plus rows appended to `docs/a11y/findings.csv` with `component` set and `owner_ticket` E47-S04.

## Out of scope
- Changing any palette value - E47-S04 owns remediation; E47-D02 owns the design of replacement values.
- Screenshot-based visual diffing of rendered canvases (too flaky; we assert on token values and on the encoding manifest instead).
- Custom user-defined palettes beyond the six shipped ones; SCR-116 already warns at selection time when a custom combination falls below 4.5:1.

## Acceptance criteria
```gherkin
Scenario: Every encoding is covered in every theme
  Given the encoding manifest and the six shipped themes
  When the matrix runs
  Then contrast-matrix.json contains a result for every encoding x theme cell
  And a missing cell fails the build rather than being skipped

Scenario: A hue-only encoding is rejected
  Given a new encoding entry is added declaring non-colour channel "none"
  When the matrix runs
  Then the build fails naming that encoding and citing WCAG SC 1.4.1

Scenario: CVD simulation catches a collision
  Given the deuteranopia transform is applied to the dark palette
  And bid green and ask red map to colours within 2:1 of each other
  Then a finding is registered at level AA, severity serious, owner_ticket E47-S04

Scenario: Failure path - forced-colors mode
  Given the OS is in Windows High Contrast mode
  When the chrome is evaluated
  Then chrome colours resolve to system colours
  And the canvas palette still resolves from design tokens, not from system colours

Scenario: AAA stretch is advisory, not blocking
  Given the buy action meets 5:1 but not 7:1 in the light theme
  Then a warning is reported and the build still passes
```

## Technical notes / design
Encoding manifest (checked in, reviewed by the Accessibility role):
```ts
type Encoding = {
  id: 'footprint.delta.positive' | 'heatmap.bid' | 'pnl.negative' | ...;
  component: `CMP-${string}`;
  fg: TokenRef; bg: TokenRef;
  kind: 'text' | 'largeText' | 'nonText';
  nonColourChannel: 'glyph' | 'sign' | 'text' | 'pattern' | 'position';
  mustDifferFrom?: Encoding['id'][];   // drives the CVD collision check
};
```
Contrast uses the WCAG 2.x relative-luminance formula on resolved token values (resolve CSS custom properties per theme from the built token JSON, not from a running browser, so the check is fast and deterministic). CVD simulation uses the standard Brettel/Vienot LMS transform matrices; the chosen matrices and their source are documented in the script header so results are reproducible and reviewable.

Gradient encodings (heatmap intensity, profile bar fill) are sampled at their declared stops (min, mid, max) rather than continuously - the stops are part of the manifest.

## Test plan
- Unit: luminance/contrast maths against published WCAG reference pairs; CVD transform against reference colour triples; manifest validation (missing channel, missing token, unknown component id).
- Integration: run the matrix against the current token set and snapshot the JSON output; a token change that lowers a ratio below threshold must fail the snapshot test with a readable diff.
- Regression: a fixture theme with a known-bad pair must always fail - guards against the check silently passing everything.
- Coverage target: >= 85% on the script (it is pure logic, no UI).

## Security notes
No new attack surface: the script reads design tokens and writes JSON. Findings output contains no user data. Per `docs/plan/04-security-program.md` this is a build-time tool; it must not be able to write outside `docs/a11y/` (asserted by path validation) so a malicious token file cannot cause arbitrary file writes in CI.

## Accessibility notes
This ticket is a pure a11y instrument; it has no UI. Its output is consumed by the SCR-116 appearance settings work in E47-S04.

## Performance notes
Runs in < 30 s on token-file change; it is a token-package CI job, not part of the per-screen sweep, so it does not consume the E47-T01 shard budget.

## Observability
Emits `a11y_contrast_failures{theme,level}` into the E47-T06 dashboard; contrast-matrix.json is retained as a CI artifact per release and is an input to the E47-T07 conformance report.

## Definition of Done
- [ ] Encoding manifest covers all listed components, reviewed and signed by the Accessibility role.
- [ ] Matrix runs in design-system CI on any token change.
- [ ] `docs/a11y/contrast-matrix.json` generated; failures routed to E47-S04 in findings.csv.
- [ ] Unit/integration tests green, coverage >= 85%.
- [ ] `docs/plan/05-accessibility-standard.md` section 5 cross-referenced from the script docs.

## Dependencies
Builds on the E05 design-system token layer and its existing text-pair linter. Feeds E47-S04 and E47-T07.

## Branch
`feat/e47-contrast-matrix`. PR size: ~350 LOC plus manifest.

## References
""" + REFS_COMMON + """- `docs/plan/11-user-stories.md` US-SET-004, US-SET-005.
- `docs/plan/14-screens-catalogue.md` SCR-116 Appearance & density settings.
""")

    # ---------------------------------------------------------------- T03
    t("E47-T03", "Task",
      "Implement the keyboard-only E2E task script as a CI suite",
      ["type/chore", "a11y", "qa", "area/design-system", "priority/p0"],
      "web", "Sprint 23", "P0 Critical", "Development", "R5 Scope",
      3, "E47", ["E47-T01"],
      """## Context
`docs/plan/05-accessibility-standard.md` section 9.4 requires "a Playwright suite that never dispatches a mouse event", driving the section 8.2 task script programmatically, so keyboard traps and focus-loss regressions are caught on every PR without waiting for a human screen-reader pass. Section 8.2 item 5 sets the severity bar this suite encodes: **a task that cannot be completed keyboard-only is a P0 release blocker for that screen**.

This is also the automated expression of US-SET-001 ("settings screen fully keyboard operable"), US-SET-002 (one global hotkey layer works in every view) and section 3.1 rule 6 (no hover-only or drag-only functionality).

## Scope / Deliverables
- `frontend/tests/a11y/keyboard/` - a Playwright project configured so that mouse APIs are hard-disabled: `page.mouse`, `locator.click()` and `hover()` are monkey-patched to throw, so a test cannot accidentally cheat. Navigation is `keyboard.press` only.
- The six section 8.2 item 3 tasks, one spec each:
  1. **Switch symbol** via the watchlist search (SCR-090/CMP-160 SymbolSearchInput) and confirm the chart (SCR-030) updates.
  2. **Place a limit order** on the order ticket (SCR-060, CMP-107) - set side, price, qty, attach SL - reach the confirm gate and submit against the paper matcher.
  3. **Read a footprint cell** two ways: via the DOM mirror on SCR-030 and via the `Alt+T` table alternative, asserting **data parity** between them for the same cell.
  4. **Navigate the DOM ladder** (SCR-050, CMP-108) - move focus by row, jump to best bid/ask, place and cancel a resting order from the ladder.
  5. **Edit a rule in both editors** - the form editor (SCR-080/CMP-145) and the node-graph editor (SCR-081/CMP-146): select a node, move it by arrow keys (the SC 2.5.7 drag alternative), connect an edge, save.
  6. **Switch Demo to Live** (SCR-071 environment switch) and confirm the confirm-dialog is fully operable and focus returns to the trigger on close.
- Cross-cutting assertions applied to every spec: no keyboard trap (focus can always reach the SkipLink CMP-085 again via Tab cycling), focus is never obscured by a sticky toolbar (SC 2.4.11 - assert the focused element's bounding box is not fully covered), focus returns to the trigger after any dialog closes, and `Esc` always cancels.
- A **focus-visibility** assertion helper: the focused element must have a computed outline/box-shadow with >= 2px width; elements with `outline: none` and no replacement fail.
- Results feed `docs/a11y/findings.csv` with source `keyboard-e2e`; a failed task registers severity `serious` and level A (SC 2.1.1).

## Out of scope
- Screen-reader output verification - Playwright cannot assert what NVDA speaks; that is E47-Q02.
- Fixing the failures this suite finds (routed to E47-S01..S06).
- Making the suite merge-blocking (E47-T06).
- Electron-shell execution; the CI suite runs headless Chromium per section 8.1 row 3, with Electron covered by the manual passes.

## Acceptance criteria
```gherkin
Scenario: The suite cannot use the mouse
  Given a spec author calls locator.click()
  When the suite runs
  Then the test fails immediately with "mouse interaction is forbidden in the
    keyboard-only suite"

Scenario: All six tasks complete keyboard-only on the remediated build
  Given the R5 release-candidate build
  When the keyboard-only suite runs
  Then all six task specs pass
  And no spec reports a keyboard trap or an obscured focus target

Scenario: Data parity between DOM mirror and table alternative
  Given the footprint cell at the focused bar and price level 64,010.0
  When the value is read from the DOM mirror and again from the Alt+T table
  Then bid volume, ask volume, delta and imbalance flag are identical in both

Scenario: Failure path - drag-only interaction
  Given the node-graph editor node can only be moved by dragging
  When task 5 attempts arrow-key repositioning
  Then the spec fails and registers a finding against WCAG SC 2.5.7 routed to
    E47-S03

Scenario: Failure path - focus lost after dialog
  Given the Demo-to-Live confirm dialog is dismissed with Esc
  When focus is queried
  Then it is on the environment-switch trigger, not on document.body
```

## Technical notes / design
Mouse lockdown:
```ts
test.beforeEach(async ({ page }) => {
  for (const m of ['click','dblclick','hover','tap','dragTo'] as const) {
    (page as any)[m] = () => { throw new Error('mouse interaction is forbidden in the keyboard-only suite'); };
  }
  await page.addInitScript(() => {
    ['mousedown','mouseup','click','pointerdown'].forEach(e =>
      window.addEventListener(e, ev => { if (ev.isTrusted) throw new Error('trusted mouse event'); }, true));
  });
});
```
Obscured-focus check: compare `document.activeElement.getBoundingClientRect()` against `document.elementFromPoint()` at the element's centre - if the topmost element is neither the focused node nor a descendant, SC 2.4.11 fails.

Order placement runs against the **paper matcher on the Demo environment** with a seeded synthetic account, never against live. The environment-switch spec (task 6) stops at the confirm dialog's operability and the announcement of the badge change; it does not actually enable Live trading.

Parity check (task 3) reads the mirror node's `aria-label`/text content and the table row cells, normalises number formatting through the same formatting utility the app uses (US-SET-006 mandates one utility everywhere), then compares.

## Test plan
- The suite *is* the test artifact. Its own correctness is guarded by: negative fixtures (a page with a deliberate keyboard trap must fail the trap assertion; a button with `outline:none` must fail the focus-visibility assertion; a mouse call must throw).
- Integration: runs against the seeded fixture feed so ladder and footprint have real levels.
- Flake: 3 consecutive green runs required before the suite is allowed into the gate set (E47-T06).
- Coverage: not line-coverage driven; coverage is expressed as "all six section 8.2 tasks implemented", asserted by a manifest test.

## Security notes
The order-placement spec transacts on the Demo environment with synthetic credentials held in CI secrets, scoped to demo only, withdrawal permission off (`docs/plan/04-security-program.md`). A misconfiguration that pointed the suite at Live would place real orders - the spec asserts `environment === 'demo'` before submit and aborts otherwise. The Demo-to-Live spec must not be able to complete the switch in CI; it asserts the dialog is operable and then cancels.

## Accessibility notes
This ticket encodes the keyboard half of the standard: SC 2.1.1 (keyboard), 2.1.2 (no trap), 2.4.3 (focus order), 2.4.7 and 2.4.11 (focus visible / not obscured), 2.5.7 (dragging alternatives), 2.5.8 (target size is checked by axe in E47-T01).

## Performance notes
Suite budget <= 6 min wall-clock in its own shard. Keyboard-driven navigation must not require artificial sleeps - use Playwright auto-waiting on focus state, so the suite does not become a timing-sensitive flake source.

## Observability
Per-task pass/fail published to the E47-T06 dashboard as `a11y_keyboard_task{task,status}`; traces and videos retained on failure.

## Definition of Done
- [ ] Six task specs merged and green 3 consecutive runs.
- [ ] Mouse lockdown and negative fixtures in place.
- [ ] Findings routed into findings.csv with correct owner tickets.
- [ ] Reviewed by the Accessibility role and QA/SDET lead.
- [ ] `docs/a11y/README.md` documents how to run and extend the suite.

## Dependencies
- **E47-T01** provides the screen manifest, fixture seeding and the findings register this suite writes into.
- Relies on the DOM mirror (E11), the `Alt+T` table alternative (section 6.3), the global hotkey layer (US-SET-002, E10) and the paper matcher (Demo).

## Branch
`feat/e47-keyboard-e2e`. PR size: one PR per two task specs, <= 400 LOC each.

## References
""" + REFS_COMMON + """- `docs/plan/11-user-stories.md` US-SET-001, US-SET-002, US-SET-003.
""")

    # ---------------------------------------------------------------- T04
    t("E47-T04", "Task",
      "Implement the motion and flash-rate audit script",
      ["type/chore", "a11y", "perf", "area/design-system", "priority/p1"],
      "web", "Sprint 23", "P1 High", "Development", "R2 Render performance",
      2, "E47", [],
      """## Context
`docs/plan/05-accessibility-standard.md` section 7.3 sets a hard, automated gate: **no content flashes more than 3 times per second** (WCAG SC 2.3.1, the seizure threshold), audited explicitly for big-trade bubble bursts, liquidation-heatmap flash, alert-toast entrance and price-flash-on-tick. The standard is blunt about why: "how easy it is for a naive flash-green/red-on-every-tick implementation to exceed 3Hz on a fast-moving symbol". On a BTCUSDT tick rate of 50/s a per-tick flash is a 50Hz strobe over the whole ladder.

Section 7.2 additionally requires that `prefers-reduced-motion: reduce` (or the in-app `Ctrl+Shift+M` override from US-SET-007) actually removes the motion, not merely shortens it.

## Scope / Deliverables
- `frontend/tests/a11y/motion/` - a frame-capture harness that drives a fixed high-tick-rate scenario (recorded BTCUSDT fixture replayed at 50 trades/s for 10 s) and captures frames at 60fps from the target surfaces.
- **Flash detection**: for each captured region, compute relative luminance per frame; count transitions where the luminance delta exceeds the WCAG general-flash threshold (>10% of full-scale and the darker state below 0.80 relative luminance); assert the count stays <= 3 in any rolling 1-second window. Regions audited: CMP-112 BigTradeBubble on SCR-030, the liquidation/heatmap flash on SCR-050 (CMP-111), CMP-165 AlertFiredToastGroup, the price-flash-on-tick in CMP-108 DomLadderRow and CMP-161 WatchlistRow, and the red-flash on CMP-117 RiskLockoutBanner.
- **Reduced-motion assertions**: with `prefers-reduced-motion: reduce` emulated and separately with the in-app override active, assert that heatmap trail fades, bubble pop/scale-in, panel open/close transitions and chart inertia are gone - measured as "zero luminance transitions above threshold and zero transform animation over the capture window", not as "a CSS class is present".
- **Pause control assertion** (SC 2.2.2): any auto-moving content running > 5 s - replay auto-play (CMP-170 ReplayScrubber), the tape scroller on SCR-055, the alert toast stack - exposes a keyboard-reachable pause control.
- Findings written to `docs/a11y/findings.csv` with source `motion-audit`, level A for SC 2.3.1 failures (severity `serious`), AA for 2.2.2.

## Out of scope
- Fixing any offending animation - routed to E47-S01 (chart canvas), E47-S02 (order-flow canvases) or E47-S05 (chrome/toasts).
- Designing the replacement motion-reduce variants - E47-D04 owns that.
- General frame-time/performance regression testing - that is E46.

## Acceptance criteria
```gherkin
Scenario: Flash rate is within the seizure threshold at full tick rate
  Given the recorded fixture replayed at 50 trades per second for 10 seconds
  When the audit analyses the DOM ladder price-flash region
  Then no rolling 1-second window contains more than 3 qualifying flashes

Scenario: Reduced motion actually removes motion
  Given prefers-reduced-motion: reduce is emulated
  When a big trade arrives and a panel is opened
  Then the bubble appears without scale-in animation
  And the panel transition completes within one frame
  And zero qualifying luminance transitions are recorded

Scenario: The in-app override matches the OS setting behaviour
  Given the OS preference is "no-preference"
  And the user enables reduced motion on SCR-117 (or presses Ctrl+Shift+M)
  Then the same assertions as the OS-emulated case pass

Scenario: Failure path - naive per-tick flash
  Given a build where the ladder flashes on every tick
  When the audit runs
  Then it fails naming the region, the measured flash rate and WCAG SC 2.3.1
  And a finding is registered routed to E47-S02

Scenario: Auto-playing replay can be paused from the keyboard
  Given replay auto-play is running
  When the tester tabs to the transport controls
  Then a pause control is reachable and activating it stops the motion
```

## Technical notes / design
Luminance is computed per WCAG relative-luminance on the captured RGB, averaged over the region of interest (regions declared as selectors or canvas sub-rects in a checked-in manifest). A "flash" is a light-to-dark-to-light or dark-to-light-to-dark pair crossing the threshold; the rolling window is evaluated at 1-frame granularity.

Capture uses Playwright's CDP screencast (or `page.screenshot` at fixed cadence where screencast is unavailable) rather than an in-page rAF hook, so we measure what is actually painted - an in-page measurement could miss compositor-driven animations.

Deliberately hostile scenario: the fixture is chosen from the recorded set with the highest trade rate available, because a quiet-market fixture would pass trivially and prove nothing.

## Test plan
- Unit: luminance maths and the rolling-window flash counter against synthetic frame sequences (exactly 3 flashes/s must pass; 4 must fail; sub-threshold deltas must not count).
- Integration: a fixture page with a known 10Hz strobe must fail; a fixture page with a 2Hz pulse must pass.
- Manual: a spot-check before each release per section 9.5, recorded in the regression checklist.
- Coverage: >= 85% on the analysis logic.

## Security notes
No product surface. Captured frames contain synthetic fixture data only and are retained as CI artifacts under the normal private artifact policy (`docs/plan/04-security-program.md`).

## Accessibility notes
Directly implements SC 2.3.1 (Three Flashes or Below Threshold, Level A), SC 2.2.2 (Pause, Stop, Hide, Level A) and SC 2.3.3 / section 7 reduced-motion requirements.

## Performance notes
Frame capture is expensive; this job runs in its own shard and on changes to animation code plus nightly, not on every PR's critical path. Budget <= 8 min. Note the audit must not itself perturb frame timing enough to mask a flash - capture cadence and any added overhead are recorded alongside results.

## Observability
`a11y_flash_rate_max{region}` gauge published to the E47-T06 dashboard; failing captures retained as video for review.

## Definition of Done
- [ ] Audit merged, running on animation-code changes and nightly.
- [ ] All six listed regions covered by a region manifest.
- [ ] Reduced-motion assertions cover both the OS setting and the in-app override.
- [ ] Unit/integration tests green, coverage >= 85%.
- [ ] Findings registered and routed; reviewed by the Accessibility role.

## Dependencies
Needs the recorded high-tick-rate fixture from the integration-test corpus. Feeds E47-S01, E47-S02, E47-S05 and the E47-T07 report.

## Branch
`feat/e47-motion-audit`. PR size ~300 LOC plus region manifest.

## References
""" + REFS_COMMON + """- `docs/plan/11-user-stories.md` US-SET-007 (reduced motion preference).
""")

    # ---------------------------------------------------------------- T05
    t("E47-T05", "Task",
      "Add focus-order and landmark accessibility-tree snapshot regression tests",
      ["type/chore", "a11y", "qa", "area/design-system", "priority/p1"],
      "web", "Sprint 23", "P1 High", "Development", "R5 Scope",
      2, "E47", ["E47-T01"],
      """## Context
`docs/plan/05-accessibility-standard.md` section 9.6 requires an accessibility-tree snapshot per top-level screen, diffed on every PR, "so unintentional landmark/heading/label changes surface as a reviewable diff rather than silent regressions". Section 8.2 item 2 makes the same check manually (landmark/structure pass). axe-core does **not** catch these: a screen can have a perfect axe score while its heading levels skip from h1 to h4, its main landmark disappears, or its tab order jumps from the order ticket back to the nav.

This ticket is the cheap, permanent guard that keeps E47's remediation from silently rotting after GA.

## Scope / Deliverables
- Snapshot tests over the 11 tracked top-level screens (the same set pinned in E47-T01) plus every settings screen SCR-110..119 and the admin entry screens SCR-120, SCR-121, SCR-125.
- Two artefacts per screen, both committed and diffed:
  1. **Landmark/heading outline** - the normalised region/landmark list and the heading tree, asserted against the section 3.4.1 expected structure: exactly one `h1`, no skipped heading levels, a `main` landmark, `navigation`, and named `region`s for each dockable panel.
  2. **Focus order** - the sequence of accessible names/roles produced by pressing `Tab` from document start until the order cycles, normalised (dynamic values such as prices and timestamps are masked to `<num>`/`<time>` so live data does not churn the snapshot).
- A **SkipLink assertion** (CMP-085): the first tabbable element on every screen is the skip link, and activating it moves focus into `main`.
- A reviewable-diff experience: snapshots are plain text, one line per node, so a PR diff reads as "heading h2 'Risk' removed" rather than as an opaque JSON blob.
- Findings routed to `docs/a11y/findings.csv` with source `tree-snapshot`, mapped to SC 1.3.1, 2.4.1, 2.4.3, 2.4.6.

## Out of scope
- Fixing structural findings (routed to E47-S05 for chrome/settings/admin, E47-S06 for trading surfaces).
- Canvas-internal structure - the DOM mirror's per-unit nodes are windowed and data-dependent; the snapshot asserts the mirror *container* exists with the right role and label, not each mirrored cell.
- Making the check blocking (E47-T06).

## Acceptance criteria
```gherkin
Scenario: Baseline snapshots exist for every tracked screen
  Given the snapshot suite runs on the R5 candidate
  Then a landmark/heading outline and a focus-order snapshot exist for each of
    the tracked screens
  And they are committed under frontend/tests/a11y/__snapshots__/

Scenario: An unintentional structural change is surfaced
  Given a PR removes the "Positions" region landmark from SCR-063
  When CI runs
  Then the snapshot test fails with a one-line diff naming the removed landmark

Scenario: Live data does not churn the snapshot
  Given SCR-030 with a streaming fixture feed
  When the snapshot is captured twice at different feed offsets
  Then the two snapshots are identical because numeric and time values are masked

Scenario: Skip link is first and functional
  Given any tracked screen
  When Tab is pressed once from document start
  Then focus is on the skip link (CMP-085)
  And activating it places focus inside the main landmark

Scenario: Failure path - heading levels skip
  Given SCR-117 jumps from h1 to h3
  Then the outline test fails citing WCAG SC 1.3.1 and registers a finding
```

## Technical notes / design
```ts
const tree = await page.accessibility.snapshot({ interestingOnly: true });
expect(outline(tree)).toMatchSnapshot(`${id}.landmarks.txt`);
expect(await tabOrder(page)).toMatchSnapshot(`${id}.focus-order.txt`);
```
`tabOrder` presses `Tab` and records `role:name` of `document.activeElement` (piercing shadow roots) until the first element repeats, with a hard cap of 300 steps to avoid hanging on a keyboard trap - hitting the cap is itself a failure and is reported as SC 2.1.2.

Masking rules are shared with the E47-T01 harness so both use one normaliser: `/[\\d,]+\\.\\d+/ -> <num>`, ISO timestamps and clock strings -> `<time>`, and any `aria-label` containing a symbol price -> masked tail.

Updating a snapshot requires an explicit `--update-a11y-snapshots` flag plus review by a CODEOWNER on the a11y path, so a regression cannot be waved through by a casual snapshot refresh - this is called out in the PR template checklist.

## Test plan
- Unit: the outline builder (skipped heading level, missing h1, duplicate landmark names), the tab-order recorder (cycle detection, cap-hit reporting), the masking normaliser.
- Integration: a fixture page with a known keyboard trap must report SC 2.1.2 at the cap; a fixture with a removed landmark must produce a readable one-line diff.
- Coverage: >= 85% on the snapshot-building logic.

## Security notes
Snapshots are committed to the repo and contain accessible names from the UI. Masking must remove numeric values, but names of *accounts* and *symbols* could still appear - the suite runs against synthetic seeded fixtures only, and a test asserts no committed snapshot matches the real-account naming pattern (`docs/plan/04-security-program.md`, data classification: internal).

## Accessibility notes
Implements the structural half of the standard: SC 1.3.1 (Info and Relationships), 2.4.1 (Bypass Blocks / skip link), 2.4.3 (Focus Order), 2.4.6 (Headings and Labels), 2.1.2 (No Keyboard Trap, via the cap).

## Performance notes
Cheap - a snapshot per screen runs in under 2 s; the whole suite fits inside the E47-T01 shard budget with no extra shard.

## Observability
Snapshot diffs appear in the PR; `a11y_structure_failures{screen}` published to the E47-T06 dashboard.

## Definition of Done
- [ ] Baselines committed for all tracked screens.
- [ ] Snapshot-update flag plus CODEOWNER rule documented in the PR template.
- [ ] Unit/integration tests green, coverage >= 85%.
- [ ] Findings routed; reviewed by the Accessibility role.

## Dependencies
- **E47-T01** supplies the screen manifest, seeding and the shared masking normaliser.
- Relies on the SkipLink (CMP-085) and landmark structure from E10.

## Branch
`feat/e47-tree-snapshots`. PR size ~300 LOC plus baselines.

## References
""" + REFS_COMMON)

    # ---------------------------------------------------------------- T08
    t("E47-T08", "Task",
      "Write ADR: canvas accessibility conformance strategy and accepted exceptions",
      ["type/docs", "a11y", "area/design-system", "priority/p1"],
      "docs", "Sprint 23", "P1 High", "Architecture", "R8 Browser/GPU compat",
      1, "E47", [],
      """## Context
`docs/plan/05-accessibility-standard.md` section 1 records canvas inaccessibility as "the primary architectural risk this document manages", and section 6 prescribes four mandatory layers (DOM mirror, live regions, table alternatives, canvas semantics fallback). That strategy is currently spread across the standard, `docs/plan/26-chart-engine-design.md` section 12 and several epics' tickets. Before remediation starts we need one durable, citable decision record - both so E47-S01/S02/S03 implement against a single agreed contract, and so any **Owner-accepted exception** carries a written compensating control rather than being an undocumented gap discovered at the PRR.

Placed early (S23) deliberately: E47-S01 is blocked on it, so canvas remediation cannot start from a verbal understanding.

## Scope / Deliverables
- `docs/plan/27-adrs/ADR-00NN-canvas-accessibility-conformance.md` (number assigned at authoring from the existing ADR index), following the repo ADR template: Status, Context, Decision, Consequences, Alternatives considered, References.
- **Decision content**: the four-layer strategy is the normative contract for every canvas-rendered surface - chart (SCR-030), footprint, volume/delta/TPO profiles, DOM liquidity heatmap (SCR-050), big-trade bubbles, and the node-graph editor (SCR-081). For each layer, the ADR states the mandatory interface: the engine's "visible window + focused unit" query surface (`26-chart-engine-design.md` section 12), the live-region throttle defaults (250 ms data cursor, 2 s per ambient field), the fixed table-alternative column sets for footprint / profile / DOM ladder (standard section 6.3), and the `role="img"` + dynamic `aria-label` fallback (section 6.4).
- **Alternatives considered and rejected**, with reasons: (a) rendering the whole surface in SVG/DOM - rejected on `docs/plan/06-performance-and-load-standard.md` frame budgets at 100k bars; (b) canvas `accessibleChildren`/AOM - rejected as not shipped in the pinned Chromium; (c) an export-only "download as CSV" accommodation - rejected because it makes SR users second-class (standard section 6.3 explicitly forbids a compliance-minimum alternative); (d) exempting power-user surfaces - rejected by standard section 1.
- **Exceptions register** section: a table of Owner-accepted exceptions with columns `{id, screen/surface, SC, why unfixable now, compensating control, owner, expiry date, follow-up ticket}`. Populated during S24-S25 as remediation concludes; the ADR is amended (not superseded) when an exception is added, and every exception requires the Owner's and the Accessibility role's recorded approval.
- Update `docs/plan/27-adrs/README.md` (ADR index) and add a back-link from `docs/plan/05-accessibility-standard.md` section 6.

## Out of scope
- Implementing any layer (E47-S01/S02/S03 own that; the engine API itself was delivered by E11).
- The published external conformance report - that is E47-T07 and is a different artefact for a different audience.
- Re-deciding the WebGL choice itself (already settled in the chart-engine ADR set).

## Acceptance criteria
```gherkin
Scenario: The ADR is normative and citable
  Given the ADR is merged with status Accepted
  Then E47-S01, E47-S02 and E47-S03 each cite it as their implementation contract
  And it specifies, for each of the four layers, the concrete interface and the
    default throttle/window values

Scenario: Rejected alternatives are recorded
  Then at least the four listed alternatives appear with the reason each was
    rejected and the evidence cited

Scenario: An exception cannot be silent
  Given a Level AA failure that cannot be fixed before GA
  When it is accepted
  Then a row exists in the exceptions register with a compensating control, a
    named owner, an expiry date and a follow-up ticket
  And the Owner and the Accessibility role have recorded approval

Scenario: Failure path - an exception without a compensating control
  Given a proposed exception whose compensating-control cell is empty
  Then the ADR review rejects it and the finding returns to open status
```

## Technical notes / design
The ADR must resolve three questions that have so far been implicit, because S01/S02 will otherwise each answer them differently:
1. **Mirror window size** - standard section 6.1 and the epic's performance note fix it at <= 200 rows/units; the ADR states this is a hard cap with a "load more" control, not a soft target.
2. **Announcement precedence** - when the data cursor (250 ms) and an ambient field (2 s) both have updates, which wins and what is dropped. Decision: assertive channel is reserved for order/fill/reject and risk events; the data cursor uses polite and replaces (not queues) its pending message; ambient fields coalesce to latest-value-wins.
3. **Parity obligation** - the table alternative and the DOM mirror must expose the same values for the same unit (this is what E47-T03 task 3 asserts); where a value is a heuristic estimate, both must carry the "(estimated)" marker and reason per standard section 6.3.

## Test plan
Documentation ticket: verified by review, not by automated test. However the ADR's normative values (200-unit window, 250 ms / 2 s throttles, fixed table columns) are asserted by tests in E47-S01/S02 and E47-Q05, so the ADR is executable in practice. A docs CI check validates the ADR template sections are all present and the index is updated.

## Security notes
The ADR should note (and E47-X01 will formally model) that the DOM mirror materialises trading data into the DOM and must respect the same RBAC scoping as the canvas, and that live regions must never announce secrets. Data classification: internal.

## Accessibility notes
The ADR *is* the accessibility architecture record. No UI.

## Performance notes
Records the budget constraints the a11y layers operate under (`docs/plan/06-performance-and-load-standard.md` budgets 1, 3, 14) so future changes cannot quietly raise the mirror window or announcement rate without revisiting the decision.

## Observability
N/A.

## Definition of Done
- [ ] ADR merged with status Accepted, numbered and indexed.
- [ ] Back-link added from `docs/plan/05-accessibility-standard.md` section 6 and from `docs/plan/26-chart-engine-design.md` section 12.
- [ ] Reviewed and approved by the Architect, the Accessibility role and a chart-engine code-owner.
- [ ] Exceptions register section present (may be empty at merge; populated by the E47 exit gate).

## Dependencies
No blocking predecessor - written from existing plan docs. Blocks E47-S01 (and is cited by S02/S03).

## Branch
`docs/e47-adr-canvas-a11y`. PR size: one document, ~200 lines.

## References
""" + REFS_COMMON + """- `docs/plan/26-chart-engine-design.md` section 12 (engine accessibility layer) and section 13 (test matrix).
- `docs/plan/27-adrs/` - existing ADR index and template.
""")
