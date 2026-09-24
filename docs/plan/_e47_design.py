# -*- coding: utf-8 -*-
"""E47 design tickets (D01-D07)."""


def build_design(t, REFS_COMMON):

    t("E47-D01", "Task",
      "Run screen-reader and keyboard-only research sessions with the owner and managers",
      ["design", "ux-research", "a11y", "type/research", "area/design-system", "priority/p2"],
      "web", "Sprint 22", "P2 Medium", "Product", "R14 User retention",
      3, "E47", [],
      """## Context
Everything E47 remediates is judged against real use, not against a checklist. `docs/plan/05-accessibility-standard.md` section 1 states the AA bar exists because (a) the owner may develop RSI/motor or vision conditions over the tool's lifetime, (b) keyboard-first operation is a *trading speed* requirement, not only an accommodation. Before we design the accessible alternatives (E47-D02, E47-D03) we need evidence about how the actual users - the owner and the two or three account managers - operate the terminal under keyboard-only and under screen-reader conditions, and where the current build breaks their task flow.

This is the only ux-research ticket in E47; its output feeds every downstream design ticket and sets the priority order for the remediation stories.

Plan references: `docs/plan/05-accessibility-standard.md` sections 1, 3, 8.2; `docs/plan/10-personas.md` (persona P3 - the accessibility-affected user, and M1 - manager); `docs/plan/13-user-flows.md` (flows F5, F6, F7, F16, F20 - the flows the task script is drawn from).

## Scope / Deliverables
- 4 moderated sessions (2 with the owner, 2 with managers), 75 minutes each, on the current R4 build in the Electron production shell.
- Session A per participant: **keyboard-only**, mouse physically unplugged. Tasks drawn from `05-accessibility-standard.md` section 8.2 item 3: switch symbol via the watchlist (SCR-100 family), place a limit order from the order ticket (SCR-070 family), inspect a footprint cell, navigate the DOM ladder, arm and disarm a rule, switch Demo to Live.
- Session B per participant: **NVDA running**, screen dimmed to 0 for the first two tasks then restored, to surface pure-audio comprehension gaps.
- One session with the Accessibility role acting as an expert-review proxy for a full-time NVDA user, since we have no such user in the owner group - documented explicitly as a proxy, not as user data.
- Deliverables: a findings deck, a prioritised friction list mapped to SCR-* ids, a "task cannot be completed" list (these become P0 findings in the E47-T01 register), and a recommended announcement-verbosity default for SCR-117.
- Research artifacts stored under `docs/research/a11y-sessions/` with consent notes; recordings are internal-only.

## Out of scope
- Recruiting external participants with disabilities (internal tool, fixed user set) - the expert-review proxy substitutes, and this limitation is stated in the conformance report (E47-T07).
- Any Android/mobile testing.
- Redesigning screens during the sessions; this ticket produces evidence only.

## Acceptance criteria
```gherkin
Scenario: Sessions completed and analysed
  Given 4 participant sessions plus 1 expert-review proxy session are scheduled
  When all sessions have run
  Then a findings deck exists with at least one observation per task in the
    section 8.2 script
  And every observation is tagged with a screen id, a severity and a WCAG success
    criterion where one applies

Scenario: Blocking tasks are escalated immediately
  Given a participant cannot complete a task keyboard-only
  When the session ends
  Then that task is filed the same day as a P0 candidate finding against the
    owning screen, without waiting for the deck

Scenario: Verbosity default is evidence-based
  Given the NVDA sessions with ambient price announcements enabled
  When participants report the announcement rate
  Then a recommended default cadence for SCR-117's "announce price updates"
    control is stated with the observed rate that motivated it

Scenario: Proxy limitation is disclosed
  Then the deck and the downstream conformance report both state that no
    full-time assistive-technology user participated, and that the expert review
    is a proxy
```

## Technical notes / design
- Environment: Electron production build pointed at **demo**, never live (`02-definition-of-ready-done.md` demo rule). Seed a realistic workspace: BTCUSDT and ETHUSDT charts, footprint on, DOM ladder open, two working orders, one open position.
- NVDA pinned to the version in `05-accessibility-standard.md` section 8.1 row 1 (NVDA 2024.x, latest stable at freeze) so observations are reproducible against the later Q02 passes.
- Use think-aloud for the keyboard sessions; use retrospective probing for the NVDA sessions (think-aloud competes with speech output).
- Record: task success/failure, time on task, number of keystrokes to reach the target control, points where focus was lost or stolen.

## Test plan
N/A (research). Validity controls instead: identical task script per participant, a single moderator, a second note-taker, and a pilot run with a team member before the first real session to shake out the seeded workspace.

## Security notes
Sessions run against demo only; no live credentials, no real API keys on screen. Recordings may contain account names and position sizes - classify as Internal per `docs/plan/04-security-program.md`, store in the internal research drive, and do not attach raw recordings to tickets. Screenshots used in the deck have account identifiers redacted.

## Accessibility notes
The research materials themselves must be accessible: the task script is provided as plain text (not only as a slide), the consent form is keyboard-operable, and participants may take breaks at any point with no timing pressure.

## Performance notes
Sessions must run on the reference hardware from `docs/plan/06-performance-and-load-standard.md` section 3.1 so that any observed sluggishness is attributable to the build, not the machine.

## Observability
N/A - no product code changes. Findings are logged into the E47 findings register (`docs/a11y/findings.csv`) once E47-T01 creates it, or into a staging sheet before then.

## Definition of Done
- [ ] 5 sessions run (4 participants plus 1 expert proxy) and notes written up within 2 working days of each.
- [ ] Findings deck published and reviewed with the Accessibility role and the CDO delegate.
- [ ] Prioritised friction list mapped to SCR-* ids and handed to E47-D02 and E47-D03.
- [ ] P0 "cannot complete" items filed as findings immediately.
- [ ] Proxy limitation documented for inclusion in the conformance report.
- [ ] Research artifacts archived with consent records.

## Dependencies
None blocking. Consumes the R4 build; informs E47-D02, E47-D03 and the triage order of E47-S01..S06.

## Branch
`design/e47-ux-research` (artifacts and notes only, no product code). PR size: docs-only.

## References
""" + REFS_COMMON + """- `docs/plan/10-personas.md` - persona P3 and M1.
- `docs/plan/13-user-flows.md` - F5, F6, F7, F16, F20.
""")

    t("E47-D02", "Task",
      "Design and validate the high-contrast and three CVD-safe palettes against every order-flow encoding",
      ["design", "a11y", "type/design", "area/design-system", "priority/p1"],
      "web", "Sprint 22", "P1 High", "Product", "R2 Render performance",
      5, "E47", ["E47-D01"],
      """## Context
SCR-116 (Appearance and density settings) already offers theme choices of dark / light / high-contrast / CVD-safe deuteranopia and protanopia / tritanopia, and US-SET-005 requires that changing convention or palette updates "every chart, DOM, heatmap, footprint, bubble and profile surface consistently" with side and direction remaining distinguishable without colour. What has never been done end-to-end is a *design-side* validation of those palettes against the full set of order-flow encodings at once: footprint delta shading and imbalance outlines, heatmap bid/ask gradient stops, CVD sign, profile bars with POC/VAH/VAL, big-trade bubbles, P&L signs, order status, risk severity and the LIVE/DEMO badge.

`docs/plan/05-accessibility-standard.md` section 4.2 makes CVD simulation for all three common types a **Definition-of-Done gate for design tickets**, and section 5.4 requires chart data-ink to meet 3:1 against the chart background *at every point in a gradient*. This ticket produces the final, validated token values that E47-T02 then enforces in CI and E47-S04 implements.

## Scope / Deliverables
- Figma Foundations update: complete token sets for `theme.high-contrast`, `theme.cvd-deuteranopia`, `theme.cvd-protanopia`, `theme.cvd-tritanopia`, aligned with the existing dark/light sets from E05.
- A validation board rendering, per palette, a real sample of each encoding surface: footprint cell grid (CMP-110 family), heatmap column strip (CMP-111 / CMP-193), volume-delta profile, CVD pane, big-trade bubbles, positions row, order-status row, P&L cell, risk-severity chip, LIVE and DEMO badges, buy/sell primary action buttons.
- Each sample run through deuteranopia, protanopia and tritanopia simulation plus a grayscale pass; grayscale is the acid test for section 4.3's "pattern-based flagging survives grayscale".
- Non-colour redundancy audit: for each encoding, name the second and third channel (glyph, sign, border pattern, axis-side convention, text label) per section 4.1's shape+text+colour triad. Anything that has only colour is a finding.
- Contrast figures computed and recorded for: body text (>= 4.5:1), large text (>= 3:1), UI component and focus ring (>= 3:1), chart data-ink against chart background at both gradient endpoints and the midpoint (>= 3:1), and the AAA stretch targets (>= 7:1) for buy/sell primary buttons and the LIVE/DEMO badge.
- Forced-colors / Windows High Contrast behaviour specified: which surfaces adopt system colours and which keep token colours with a documented rationale.
- Output handed to engineering as the authoritative token values plus a pass/fail matrix; SCR-116's live preview tile (CMP-228) updated to show a footprint cell, a ladder row and a positions row under each new palette.

## Out of scope
- Implementing the palettes in code (E47-S04) or the CI linter (E47-T02).
- Changing the default green=bid / red=ask convention (owner decision OD#10) - the CVD palettes are alternatives, not replacements.
- Print/export colour profiles.

## Acceptance criteria
```gherkin
Scenario: Every palette passes the contrast matrix
  Given the four palettes designed in this ticket
  When the contrast matrix is computed for every token pair in the validation board
  Then every text pair is at least 4.5:1, every large-text pair at least 3:1 and
    every UI-component, focus-ring and data-ink pair at least 3:1
  And the buy/sell primary buttons and the LIVE/DEMO badge reach at least 7:1 in
    the high-contrast palette

Scenario: Gradients pass at every stop, not only at the ends
  Given the heatmap bid and ask gradients in each palette
  When contrast is sampled at the low, mid and high intensity stops
  Then each sampled stop meets at least 3:1 against the chart background
  And any stop that fails is respecified before sign-off

Scenario: Grayscale preserves meaning
  Given every validation-board sample rendered in grayscale
  When a reviewer who has not seen the colour version reads it
  Then buy versus sell, bid versus ask, imbalanced versus normal cells, and
    profit versus loss remain distinguishable via glyph, sign, border pattern or
    text alone

Scenario: A colour-only encoding is caught
  Given an encoding whose only differentiator is hue
  When the CVD simulation pass runs
  Then it is recorded as a finding with the required second and third channel
    specified, and it blocks sign-off of this ticket

Scenario: Forced-colors is specified, not left to chance
  Given Windows High Contrast mode is active
  Then the specification states, per surface, whether system colours are adopted
    or token colours retained, with a rationale for each canvas surface
```

## Technical notes / design
- Simulation tooling: Stark or Able in Figma plus Chrome DevTools vision-deficiency emulation as a cross-check (both named in `05-accessibility-standard.md` section 4.2). Record which tool produced which result.
- Contrast maths uses WCAG 2.x relative luminance; for gradients, sample at stops 0.0 / 0.5 / 1.0 of the normalised intensity ramp.
- Dark theme rule from section 5.5: near-black background (not `#000`) and off-white text (not `#FFF`); the high-contrast palette raises ratios but must not introduce pure black on pure white either.
- Token naming follows the E05 Style Dictionary structure so E47-S04 is a data change plus a theme registration, not a new theming mechanism.
- Density interaction: the validation board is drawn at both `compact` and `comfortable` density; compact must still meet the >= 24 px target rule or carry a documented essential exception per section 3.4.7.

## Test plan
Design-side verification: the pass/fail matrix is regenerated from the exported tokens by the E47-T02 script before sign-off, so the design file and the computed matrix must agree. Any disagreement is resolved in favour of the computed matrix. Reviewer checklist: Accessibility role, one order-flow product designer, one frontend engineer who will implement E47-S04.

## Security notes
N/A - no data handling. The validation board uses synthetic market data, never real account or position values.

## Accessibility notes
This ticket is a pure accessibility deliverable. Note the section 4.1 rule that colour is a *reinforcing* channel only; the palette work must not be used to justify removing a glyph or a text label anywhere.

## Performance notes
Palette changes must remain CSS custom-property swaps applied within one frame and must not remount panels or drop the GL context (SCR-116 performance note). No palette may require an extra texture upload or a per-frame recomputation on the canvas surfaces.

## Observability
N/A - design artifact. Downstream, `appearance.chart_palette_changed` analytics (already specified on SCR-116) will show uptake.

## Definition of Done
- [ ] Four palettes complete in the Figma Foundations file, named per the E05 token structure.
- [ ] Validation board covers every encoding listed in Scope, at both densities.
- [ ] CVD simulation (3 types) plus grayscale pass executed and attached.
- [ ] Contrast matrix computed, all pairs passing, AAA stretch targets met or an exception recorded.
- [ ] Forced-colors behaviour specified per surface.
- [ ] Non-colour redundancy audit complete with no colour-only encodings remaining.
- [ ] SCR-116 preview tile updated.
- [ ] Sign-off recorded by the Accessibility role (required per `05-accessibility-standard.md` section 11.7) and the CDO delegate.
- [ ] Tokens exported and handed to E47-T02 and E47-S04.

## Dependencies
- E47-D01 for the friction list (which encodings participants actually misread).
- Relies on the E05 token architecture and Style Dictionary build.
- Blocks E47-S04 (implementation) and feeds E47-T02 (CI enforcement).

## Branch
`design/e47-palettes` for exported token JSON and the matrix artifact. PR size: token files plus docs, small.

## References
""" + REFS_COMMON + """- `docs/plan/14-screens-catalogue.md` SCR-116 - appearance and density settings, preview tile, design sign-off checklist.
- `docs/plan/11-user-stories.md` US-SET-004, US-SET-005.
- `docs/plan/16-design-system-brief.md` - token layer and theming.
""")

    t("E47-D03", "Task",
      "Produce hi-fi designs for the accessible-alternative patterns on canvas surfaces",
      ["design", "a11y", "type/design", "area/design-system", "priority/p1"],
      "web", "Sprint 22", "P1 High", "Product", "R2 Render performance",
      5, "E47", ["E47-D01"],
      """## Context
`docs/plan/05-accessibility-standard.md` section 6 mandates three complementary layers for every canvas-rendered surface: an offscreen DOM mirror (6.1), throttled ARIA live regions (6.2) and a "View as table" data alternative (6.3). The engine already ships a data cursor and a 200-row hidden table (`docs/plan/26-chart-engine-design.md` section 12) and US-CHART-014 specifies the chart's tabular alternative. What is missing is a *consistent designed pattern*: today each canvas surface would invent its own toggle affordance, table columns, empty state and focus behaviour.

This ticket designs the shared pattern once - the toggle control, the table shell, the summary-announcement phrasing, the focus-and-return contract - so E47-S01, E47-S02 and E47-S03 implement one pattern rather than five. Per `05-accessibility-standard.md` section 6.3 the table alternative is an **equal-status alternative, not a degraded fallback** (also stated as the NFR on US-CHART-014); the design must read that way.

## Scope / Deliverables
Hi-fi Figma designs plus a written pattern spec covering:
- **The alternative-view toggle**: placement, label ("View as table"), keyboard shortcut surfacing, state persistence, and its relationship to the SCR-117 setting "always show data-table alternatives". Applies on chart panes, the footprint grid, the volume/delta/TPO profile pane, the DOM ladder and heatmap, and the CVD pane.
- **The table shell**: column sets per surface - chart bars (time, open, high, low, close, volume, delta, POC, flags per US-CHART-014); footprint (price level, bid volume, ask volume, delta, imbalance flag); profile (price level, volume, is-POC, in-value-area); heatmap (time column, price, resting size, side); DOM ladder (price, bid size, ask size, own orders, position marker). Sticky headers, row virtualisation affordance, and the "showing rows N-M of the visible range" status line.
- **Sync contract, drawn**: crosshair to focused row and back (US-CHART-014 "Sync" scenario) - what the focused row looks like, what the canvas shows when the table has focus.
- **Summary announcement phrasing**: the exact sentence templates for the chart data cursor ("14:32, close 64,210, delta -128, imbalance stacked sell x3" per `26-chart-engine-design.md` section 12), the range summary (trend, range, notable flags), the footprint cell, the heatmap cell and the ladder row. Templates are specified as fill-in strings so implementation cannot improvise wording.
- **Live-region politeness map**, drawn as a table: which event classes are polite-ambient, which are assertive, and how the SCR-117 verbosity control (off / on significant change / always) and the master "reduce announcements" toggle change the mapping.
- **Focus surrogate visuals**: how a focused bar, footprint cell, heatmap cell or ladder row looks on the canvas when the invisible surrogate has focus (CMP-039 FocusRing on a canvas-adjacent surrogate), including the >= 24 px effective target size and the essential-exception case for the densest footprint zoom levels with its compensating control.
- **Empty, loading, no-data-in-range and degraded states** for the table alternative.

## Out of scope
- Implementation (E47-S01, E47-S02, E47-S03).
- The rule node-graph editor's own keyboard model - that is designed already in `15-component-catalogue.md` CMP-152 family and is only *verified* in E47-S03, not redesigned here. This ticket covers its "switch to form view" affordance only insofar as it matches the shared toggle pattern.
- New data content that the canvas does not already compute.

## Acceptance criteria
```gherkin
Scenario: One pattern, five surfaces
  Given the pattern spec produced by this ticket
  When a designer or engineer looks up the alternative-view treatment for the
    chart, the footprint grid, the profile pane, the DOM ladder or the heatmap
  Then each resolves to the same toggle affordance, the same table shell and the
    same focus-and-return contract, differing only in the column set

Scenario: Equal status, not a fallback
  Given the table alternative for any surface
  Then it exposes every value the canvas encodes visually for the focused range,
    including delta sign, imbalance flags and POC or value-area membership
  And no element of the design labels or positions it as degraded, legacy or
    "simplified"

Scenario: Announcement templates are literal
  Given the announcement spec
  When an engineer implements the chart data cursor
  Then the sentence template, the field order, the rounding and the units are
    fully specified with a worked example, leaving no wording decision to
    implementation

Scenario: Dense-zoom target size is resolved explicitly
  Given the footprint grid at its densest supported zoom level
  Then the design either meets the 24 px minimum target for the focus surrogate,
    or documents an essential exception with a named compensating control such
    as a keyboard-only cell stepper plus the table alternative

Scenario: Verbosity off still leaves the data reachable
  Given the SCR-117 verbosity control set to off
  When the user focuses a bar or a cell
  Then nothing is announced ambiently, and the design shows how the user still
    reads the value on demand via the table alternative or an explicit
    read-current-value action
```

## Technical notes / design
- The toggle must not be a hover-only or drag-only affordance (section 3.1 rule 6).
- The table is virtualised; the design must show only the currently materialised window and a status line, because the mirror is windowed to match the engine's LOD/culling (section 6.1, `26-chart-engine-design.md` section 12 caps the mirror at 200 rows).
- Live regions are pre-rendered empty containers whose text content is swapped, never destroyed and recreated (section 6.2 region hygiene) - the design must not imply a panel that mounts and unmounts.
- Focus must never be silently stolen by a streaming update (section 8.2 task 4 checks this); the design states where focus goes when the visible range scrolls out from under the focused row.
- Reduced-motion: the toggle transition ships a `motion-safe` / `motion-reduce` pair per `15-component-catalogue.md` section 0.3 rule 5.

## Test plan
Design verification: a walkthrough with the Accessibility role and the chart-engine lead against the section 6 layer list, confirming each of layers 1, 2 and 3 is addressed for each of the five surfaces. Prototype the chart-pane case in Figma and dry-run the section 8.2 footprint task against the prototype before sign-off.

## Security notes
The mirror and the table surface the same data as the canvas and must respect the same RBAC scoping - the design must not introduce a table column that exposes a field the visible surface does not (for example another account's position). Flagged here so E47-X01's STRIDE has a concrete artifact to review.

## Accessibility notes
This is the core accessibility design artifact of the epic. It must satisfy WCAG 2.2 SC 1.1.1 (non-text content), 1.3.1 (info and relationships), 2.1.1 (keyboard), 2.4.3 (focus order), 2.4.7 and 2.4.11 (focus visible / not obscured), 2.5.8 (target size minimum) and 4.1.3 (status messages).

## Performance notes
The designed pattern must be implementable inside the budgets in `docs/plan/06-performance-and-load-standard.md` (budget 1: 16.6 ms p95 frame time; budget 14: 100 ms heatmap cadence). Concretely: the table alternative renders at most the visible window, the mirror is capped at 200 rows, and announcements are throttled to 1 per 250 ms for the cursor and 1 per 2 s per ambient field. Any design element implying an unbounded DOM is rejected at review.

## Observability
Design specifies that toggling the alternative view emits `a11y.preference_changed {key:"table_alternative", value}` where it is a persisted preference, consistent with the SCR-117 analytics contract.

## Definition of Done
- [ ] Hi-fi frames for all five surfaces plus the shared table shell, in dark, light and high-contrast palettes.
- [ ] Written pattern spec with announcement templates, politeness map and focus contract.
- [ ] Empty, loading, no-data and degraded states drawn.
- [ ] Dense-zoom target-size resolution recorded (met, or exception with compensating control).
- [ ] Walkthrough completed with the Accessibility role and chart-engine lead; sign-off recorded.
- [ ] Handed to E47-S01, E47-S02 and E47-S03; pattern entry added to the design-system docs via E47-D06.

## Dependencies
- E47-D01 (research friction list).
- Consumes the existing engine contract in `26-chart-engine-design.md` section 12 and the CMP-110 / CMP-111 / CMP-193 a11y contracts in `15-component-catalogue.md`.
- Blocks E47-S01, E47-S02, E47-S03.

## Branch
`design/e47-alt-patterns` (spec markdown under `docs/design/a11y-patterns.md` plus exported frames).

## References
""" + REFS_COMMON + """- `docs/plan/11-user-stories.md` US-CHART-014 (accessible chart data alternative), US-SET-007 (accessibility preferences).
- `docs/plan/14-screens-catalogue.md` SCR-117 - accessibility settings.
- `docs/plan/26-chart-engine-design.md` section 12 - focusable chart, data cursor, DOM mirror.
- `docs/plan/15-component-catalogue.md` CMP-039 FocusRing, CMP-110 footprint cell mirror, CMP-111 heatmap cell, CMP-193 HeatmapOverlay.
""")

    t("E47-D04", "Task",
      "Audit motion and flash across the app and specify the missing motion-reduce pairs",
      ["design", "a11y", "motion", "type/design", "area/design-system", "priority/p2"],
      "web", "Sprint 22", "P2 Medium", "Product", "R2 Render performance",
      3, "E47", [],
      """## Context
`docs/plan/05-accessibility-standard.md` section 7 requires reduced-motion coverage and caps flashing at fewer than 3 flashes per second (WCAG 2.3.1), and `15-component-catalogue.md` section 0.3 rule 5 makes a `motion-safe` / `motion-reduce` pair a condition of a component shipping at all. US-SET-007 specifies that when reduced motion is on, "heatmap fades, panel transitions and chart inertia are disabled or replaced with instant changes". The photosensitivity risk in a trading terminal is real and concentrated: price-flash-on-update cells, big-trade bubbles popping in, the heatmap trail fade, and toast entry animations can all coincide during a volatile burst.

This ticket is the design-side census: enumerate every animated surface, decide its reduced-motion counterpart, and identify flash-rate hazards so E47-T04 can encode them as an automated assertion and E47-S01/S05 can implement the fixes.

## Scope / Deliverables
- A motion inventory table: every animated property change in the app, with source component (CMP-*), duration, easing, trigger frequency and whether a `motion-reduce` variant currently exists.
- For each entry with no `motion-reduce` variant: the specified replacement (instant change, opacity-only change, or removal) and which token pair it uses.
- Flash-hazard list with the worst-case trigger scenario per surface - specifically: price-flash cells in the positions and orders grids, the DOM ladder last-trade column, big-trade bubbles (CMP family per the BIG domain), the heatmap trail fade, alert toasts (CMP-045 / CMP-212 family) and rule-trigger banners.
- The representative high-tick-rate scenario definition that E47-T04 will replay in CI: symbol, tick rate, duration and which panels are visible. This must be the same scenario the automated check uses, so design and CI agree on what "worst case" means.
- Specification of the OS-level `prefers-reduced-motion` detection default and the explicit in-app override on SCR-117 (the SCR-117 sign-off checklist already requires this to be drawn).
- Decision, recorded, on whether any animation lasting more than 5 seconds exists and therefore needs a pause control (section 7 and WCAG 2.2.2).

## Out of scope
- Implementing the pairs (E47-S01 for canvas surfaces, E47-S05 for chrome).
- Writing the CI luminance-analysis script (E47-T04).
- Adding *new* motion for delight - this ticket removes and tames motion, it does not add any.

## Acceptance criteria
```gherkin
Scenario: The inventory is complete
  Given the component catalogue and the shipped app
  When the motion inventory is compiled
  Then every animated property change in the shipped build appears as a row
  And every row states whether a motion-reduce variant exists today

Scenario: Every gap gets a specified replacement
  Given a row with no motion-reduce variant
  Then the specification names the exact reduced behaviour and its token, rather
    than saying only "disable animation"

Scenario: Flash hazards are quantified, not assumed
  Given the representative high-tick-rate scenario
  When the hazard list is compiled
  Then each listed surface has an estimated worst-case flash rate and a stated
    mitigation if that estimate approaches 3 per second

Scenario: Reduced motion is honoured without losing information
  Given reduced motion is enabled
  When a price updates, a big trade prints and an alert fires
  Then each still produces a perceivable non-motion signal - a colour or value
    change, a glyph, or text - so no information is conveyed by motion alone

Scenario: Long animation needs a control
  Given any animation that runs longer than 5 seconds or loops
  Then the specification provides a pause, stop or hide control, or the
    animation is removed
```

## Technical notes / design
- Motion tokens come from `16-design-system-brief.md` section 7; a reduced variant is a token swap, not a branch in component logic, wherever possible.
- The heatmap trail fade is a canvas-side effect, not CSS - its reduced-motion variant is a renderer flag (trail length fixed, no per-frame alpha ramp), which is why the fix lands in E47-S01 rather than in a stylesheet.
- Price-flash-on-update: the reduced variant is a static background tint held for the same duration, or the SCR-117 "disable flash-on-update" option, which already exists as a designed control.
- Flash-rate estimation method: flashes per second per surface equals update events per second times flashes per event, evaluated over any 1-second window in the representative scenario.

## Test plan
Design-side: replay the representative scenario against the current build with screen capture, step frames, and count luminance transitions manually for the three worst surfaces to sanity-check the estimates that E47-T04 will later automate. Discrepancies between the manual count and the automated count are reconciled before E47-T04 is considered done.

## Security notes
N/A.

## Accessibility notes
Covers WCAG 2.2 SC 2.2.2 (pause, stop, hide), 2.3.1 (three flashes or below threshold) and 2.3.3 AAA (animation from interactions) as a stretch. Also serves vestibular-disorder users, not only photosensitive users - the specification should prefer opacity and colour changes over transforms in reduced mode.

## Performance notes
Removing motion under `motion-reduce` must measurably reduce frame work, not merely look static - SCR-117 states this explicitly ("disabling animations removes transition work from the frame budget entirely, a measurable reduction, not just a visual change"). E47-Q05 measures the delta.

## Observability
No new events. The existing `a11y.preference_changed {key:"reduced_motion"}` analytics covers uptake.

## Definition of Done
- [ ] Motion inventory table complete and reviewed against the component catalogue.
- [ ] Every gap has a specified reduced variant with a named token.
- [ ] Flash-hazard list with worst-case rates and mitigations.
- [ ] Representative high-tick-rate scenario defined and handed to E47-T04.
- [ ] SCR-117 OS-detection and override behaviour specified.
- [ ] Manual frame-count sanity check performed on the three worst surfaces.
- [ ] Accessibility-role sign-off recorded.

## Dependencies
None blocking. Feeds E47-T04, E47-S01, E47-S05 and E47-D05.

## Branch
`design/e47-motion-audit` (spec document under `docs/design/a11y-motion.md`).

## References
""" + REFS_COMMON + """- `docs/plan/11-user-stories.md` US-SET-007 - accessibility preferences, motion scenario.
- `docs/plan/14-screens-catalogue.md` SCR-117.
- `docs/plan/16-design-system-brief.md` section 7 - motion tokens.
""")

    t("E47-D05", "Task",
      "Run the epic accessibility design review and record the sign-off gate",
      ["design", "a11y", "type/design", "area/design-system", "priority/p1"],
      "web", "Sprint 23", "P1 High", "Product", "R5 Scope",
      2, "E47", ["E47-D02", "E47-D03", "E47-D04"],
      """## Context
`docs/plan/05-accessibility-standard.md` section 11.7 is a hard gate: a screen's design ticket cannot reach Done without the Accessibility role's sign-off against section 4.2 (CVD simulation) and a completed acceptance-criteria template from section 10. E47's three substantive design tickets (D02 palettes, D03 alternative patterns, D04 motion) are individually reviewed, but the epic also needs one consolidated review that checks them *against each other* - for example, that the high-contrast palette does not make the focus surrogate ring indistinguishable from the imbalance outline pattern, or that the reduced-motion variant of the price flash still satisfies the non-colour-alone rule.

This is the gate that unblocks the design handoff (E47-D06) and therefore the chrome and trading remediation stories.

## Scope / Deliverables
- A single consolidated review session with the Accessibility role, the CDO delegate, the chart-engine lead and the frontend a11y champion.
- Cross-artifact conflict check: palette x focus indicators x imbalance patterns x motion variants x density modes, at both `compact` and `comfortable`.
- A completed `a11y_acceptance_criteria` block (template at `05-accessibility-standard.md` section 10) for each of the five canvas surfaces and for the settings screens SCR-116 and SCR-117.
- Every design sign-off acceptance checklist item from SCR-116 and SCR-117 in `14-screens-catalogue.md` ticked or explicitly waived with a reason.
- A written sign-off comment naming the individual who signed, the date, and the artifact versions signed.
- Any unresolved item becomes either a change request back to D02/D03/D04 or a recorded, owner-approved exception with a compensating control (feeding E47-T08's ADR).

## Out of scope
- Reviewing implementation (that is E47-D07 design QA).
- Reviewing screens whose design did not change in this epic - they are audited mechanically by E47-T01, not re-reviewed by design.

## Acceptance criteria
```gherkin
Scenario: Cross-artifact conflicts are found before implementation
  Given the palette, alternative-pattern and motion specifications
  When they are reviewed together at both densities and in all six palettes
  Then any combination where two accessibility affordances collide is recorded
    as a change request with a named owner and a target date

Scenario: Acceptance-criteria templates are concrete
  Given a completed section 10 template for a surface
  Then it names the specific keys, roles, announcements and contrast values for
    that surface
  And a template left at boilerplate is rejected as a Definition-of-Ready
    failure per the standard

Scenario: Sign-off is attributable
  When the gate is passed
  Then the sign-off comment names an individual, a date and the exact artifact
    versions, not a team or a floating link

Scenario: Failure path - an unresolvable conflict
  Given a conflict that cannot be resolved inside the R5 window
  Then it is recorded as an owner-approved exception with a compensating control
    and a post-GA remediation ticket, and the conformance report will list it
```

## Technical notes / design
Review runs against exported artifacts with fixed version numbers, not against live Figma links, so the sign-off refers to something immutable. Use the section 8.1 pinned NVDA version for any live spot-check during the review.

## Test plan
The review itself is the verification step. Its output is checked by confirming that every SCR-116 and SCR-117 design sign-off checklist item in `14-screens-catalogue.md` has a recorded state.

## Security notes
Any exception recorded here that touches a trading safety gate (confirm policy, arm toggle, environment badge) must be co-signed by the Security engineer, since accessibility accommodations must never weaken those gates. Cross-referenced by E47-X02.

## Accessibility notes
This ticket is the section 11.7 gate itself.

## Performance notes
The review confirms no designed affordance violates the budgets cited in E47-D03 and E47-D04; anything doubtful is handed to E47-Q05 for measurement rather than approved on assumption.

## Observability
N/A.

## Definition of Done
- [ ] Consolidated review held with all four required reviewers present.
- [ ] Cross-artifact conflict list produced and every item dispositioned.
- [ ] Section 10 templates completed for five canvas surfaces plus SCR-116 and SCR-117.
- [ ] SCR-116 and SCR-117 design sign-off checklists fully dispositioned.
- [ ] Attributable sign-off comment recorded on this ticket.
- [ ] Exceptions, if any, routed to E47-T08 for the ADR and co-signed by Security where safety gates are involved.

## Dependencies
- E47-D02, E47-D03, E47-D04 must be complete.
- Blocks E47-D06 (handoff), which in turn blocks E47-S05 and E47-S06.

## Branch
`design/e47-signoff` (review record document only).

## References
""" + REFS_COMMON + """- `docs/plan/05-accessibility-standard.md` sections 10 and 11.7 - acceptance-criteria template and the sign-off gate.
- `docs/plan/14-screens-catalogue.md` SCR-116, SCR-117 design sign-off checklists.
""")

    t("E47-D06", "Task",
      "Publish the engineering handoff and contribute the a11y patterns to the design system",
      ["design", "handoff", "a11y", "type/design", "area/design-system", "priority/p1"],
      "web", "Sprint 23", "P1 High", "Product", "R5 Scope",
      3, "E47", ["E47-D05"],
      """## Context
E47's design output is only useful if it becomes reusable design-system material rather than a one-off deck. `docs/plan/05-accessibility-standard.md` section 11 makes the design system the enforcement mechanism for component-level accessibility: token layer, built-in component ARIA contracts, motion pairs, density modes, documentation requirements. This ticket converts D02's palettes, D03's alternative-view pattern and D04's motion variants into permanent design-system entries with keyboard-interaction and accessible-name tables, and produces the handoff engineering will actually build from.

Without this step, the next new screen after GA re-derives the same decisions and re-introduces the same findings.

## Scope / Deliverables
- **Handoff package** for E47-S01..S06: redlines, token references, announcement templates, keyboard tables, and a per-story mapping of which spec section governs which remediation.
- **Design-system contributions**:
  - New/updated pattern entry "Accessible alternative for canvas surfaces" documenting the toggle, table shell, sync contract and focus behaviour, cross-linked from CMP-110, CMP-111, CMP-193 and the CMP-180..199 chart-primitive band.
  - Updated component docs for CMP-039 FocusRing (surrogate usage on canvas), CMP-085 SkipLink (landmark coverage), CMP-062 ThemeSwitcher and CMP-063 DensityToggle (new palette options), CMP-228 PreviewTile (new palette previews).
  - A "keyboard interaction" table and an "accessible name/role" table for every component touched, per `05-accessibility-standard.md` section 11.6.
  - Motion token pairs registered so no component can ship with a hard-coded animation (section 11.4).
- **Storybook stories** specified (not implemented) for each contributed pattern: default, focused-surrogate, table-alternative-open, reduced-motion, high-contrast, each CVD palette.
- **Update to `docs/plan/16-design-system-brief.md`** where the shipped decisions differ from the brief, and a note in `docs/plan/15-component-catalogue.md` for each touched CMP entry.

## Out of scope
- Writing the component code or the Storybook stories themselves (those land inside the remediation stories and E05-owned component packages).
- Re-opening decisions signed off in E47-D05.

## Acceptance criteria
```gherkin
Scenario: Engineering can build without asking
  Given the handoff package
  When an engineer picks up E47-S01, S02, S03, S05 or S06
  Then every value they need - tokens, announcement strings, keyboard chords,
    ARIA roles, focus order - is in the package
  And the story body points to the specific spec section rather than to a person

Scenario: Patterns are reusable, not epic-local
  Given the design-system documentation after this ticket
  When a designer starts a new canvas-backed surface after GA
  Then the accessible-alternative pattern entry is discoverable from the
    component catalogue and specifies the full contract

Scenario: Every touched component documents its keyboard and naming contract
  Given the list of components touched by E47
  Then each has a keyboard-interaction table and an accessible-name/role table
    in its design-system entry

Scenario: Failure path - a spec gap found during implementation
  Given an engineer reports a value missing from the handoff
  Then the gap is filled in the design-system entry itself, not only in a ticket
    comment, and the handoff version is incremented
```

## Technical notes / design
- Token references are given as token names, never as hex values, so a later palette change propagates.
- Announcement templates are delivered as an i18n-shaped message catalogue entry (key plus interpolation slots), so wording can be reviewed and changed without touching render code.
- Keyboard tables follow the WAI-ARIA APG format already used across `15-component-catalogue.md`.

## Test plan
Handoff acceptance is verified by a dry-run: one frontend engineer attempts to implement a slice of E47-S05 using only the package. Any question raised is a defect in the handoff and is fixed before this ticket closes.

## Security notes
The handoff must state the rule that announcements never read secrets and that the DOM mirror is RBAC-scoped, so implementers inherit the constraint from the spec rather than needing the threat model. Cross-reference E47-X01.

## Accessibility notes
The handoff is itself the accessibility contract for the remediation work. Documentation must meet the same bar: tables readable as tables, images with alt text, no meaning conveyed by colour in the redlines.

## Performance notes
Handoff restates the hard constraints - mirror capped at 200 rows, cursor announcements at 1 per 250 ms, ambient at 1 per 2 s, palette swaps within one frame with no GL-context loss - so they are enforced at implementation time.

## Observability
Handoff specifies the analytics/audit events each remediated surface must keep emitting (for example `a11y.preference_changed`), so remediation does not silently drop instrumentation.

## Definition of Done
- [ ] Handoff package published and versioned.
- [ ] Design-system pattern entry created and cross-linked from the relevant CMP entries.
- [ ] Keyboard-interaction and accessible-name tables complete for every touched component.
- [ ] Motion token pairs registered.
- [ ] Storybook story list specified per contributed pattern.
- [ ] `16-design-system-brief.md` and `15-component-catalogue.md` updated where shipped behaviour diverges.
- [ ] Dry-run implementation check passed with no unanswered questions.
- [ ] CDO delegate and Accessibility role sign-off recorded.

## Dependencies
- E47-D05 sign-off.
- Blocks E47-S05 and E47-S06 (the stories that consume design directly); S01-S03 consume E47-D03 and can start earlier.

## Branch
`design/e47-handoff` (docs and catalogue updates).

## References
""" + REFS_COMMON + """- `docs/plan/05-accessibility-standard.md` section 11 - design-system requirements.
- `docs/plan/15-component-catalogue.md` CMP-039, CMP-062, CMP-063, CMP-085, CMP-110, CMP-111, CMP-193, CMP-228.
- `docs/plan/16-design-system-brief.md`.
""")

    t("E47-D07", "Task",
      "Design-QA the remediated screens against the signed-off accessibility specification",
      ["design", "design-qa", "a11y", "type/design", "area/design-system", "priority/p1"],
      "web", "Sprint 25", "P1 High", "Product", "R5 Scope",
      3, "E47", ["E47-S05", "E47-S06"],
      """## Context
Design QA closes the loop: E47-D05 signed off a specification, E47-S01..S06 implemented against it, and this ticket verifies that what shipped is what was signed. `docs/plan/02-definition-of-ready-done.md` requires design sign-off as a Story DoD item, and R5's quality gates (`30-release-roadmap.md` section 9.4) require the conformance report to be defensible. A report generated from an implementation that quietly diverged from the signed design would not be.

This is distinct from E49's general design-QA sweep: E47-D07 checks only the accessibility-specific deltas - focus indicators, surrogate targets, palette values, alternative-view affordances, motion variants, announcement wording.

## Scope / Deliverables
- Pixel-and-behaviour review of every screen touched by E47-S01..S06 against the E47-D05-signed artifacts, in dark, light, high-contrast and the three CVD palettes, at both densities.
- Verification that announcement wording in the build matches the D03 templates literally (field order, rounding, units).
- Verification of focus-indicator rendering: >= 3:1 ring contrast, 2 px offset, `:focus-visible` only (CMP-039 contract), including on canvas surrogates.
- Verification of the alternative-view toggle placement, label and persistence on all five canvas surfaces.
- Verification of the motion-reduce variants listed in the E47-D04 inventory, with reduced motion both OS-driven and app-override-driven.
- A findings list with severities; each finding is either fixed before sign-off or recorded as an accepted deviation with a rationale.
- Final design sign-off comment for the epic.

## Out of scope
- Functional QA (E47-Q02, E47-Q03, E47-Q04).
- Non-accessibility visual polish (E49).
- Re-litigating signed decisions.

## Acceptance criteria
```gherkin
Scenario: Implementation matches the signed design
  Given the remediated build and the signed artifacts
  When each touched screen is reviewed in all six palettes at both densities
  Then every divergence is recorded as a finding with a screen id and a severity

Scenario: Announcement wording matches the template exactly
  Given a focused chart bar, footprint cell, heatmap cell and ladder row
  When the announced string is captured
  Then it matches the D03 template including field order, rounding and units

Scenario: Focus indicators meet the contract everywhere
  Given every focusable element including canvas surrogates
  When focus is moved by keyboard
  Then the ring is visible, at least 3:1 against adjacent colours, offset by 2 px
  And it does not appear on mouse click alone

Scenario: Failure path - a deviation that cannot be fixed in time
  Given a divergence found late in Sprint 25
  Then it is recorded as an accepted deviation with a rationale, an owner and a
    post-GA ticket, and it appears in the conformance report

Scenario: Reduced motion honoured from both sources
  Given reduced motion enabled at the OS level, and separately via SCR-117
  Then in both cases every entry in the motion inventory renders its reduced
    variant
```

## Technical notes / design
- Review on the Electron production build, demo environment, seeded with the same workspace used in E47-D01 so conditions are comparable.
- Capture evidence as screenshots per palette; store alongside the conformance-report artifacts so E47-T07 can cite them.
- Use the E47-T02 computed matrix as the authority for contrast numbers rather than eyeballing.

## Test plan
Checklist-driven review with the checklist derived mechanically from the D05 sign-off record, so no signed item can be skipped. Second reviewer spot-checks 20 percent of items independently; disagreement rate above 10 percent triggers a full re-review.

## Security notes
Confirm that no accessibility affordance added during remediation bypasses a confirm gate or exposes data beyond the user's RBAC scope - if any is found, it is a P0 finding and is routed to E47-X02 as well as fixed.

## Accessibility notes
The review is conducted keyboard-only for the interaction portions, so the reviewer experiences the same path the user does.

## Performance notes
Note any visible frame-rate degradation on the canvas surfaces during review and hand it to E47-Q05 for measurement; do not accept or reject on subjective impression.

## Observability
Verify the analytics events listed in the D06 handoff still fire after remediation (`a11y.preference_changed`, `appearance.*`).

## Definition of Done
- [ ] Every screen touched by E47-S01..S06 reviewed in six palettes at two densities.
- [ ] Announcement wording verified against templates.
- [ ] Focus-indicator contract verified including on canvas surrogates.
- [ ] Motion variants verified from both OS and in-app sources.
- [ ] Findings dispositioned (fixed or accepted with rationale and post-GA ticket).
- [ ] Evidence screenshots stored for the conformance report.
- [ ] Final epic design sign-off recorded by the Accessibility role and CDO delegate.

## Dependencies
- E47-S05 and E47-S06 (the last remediation stories to land); reviews S01-S04 output as well.
- Blocks E47-Q04 (QA sign-off) because QA sign-off requires design sign-off to be in place.

## Branch
`design/e47-design-qa` (findings record and evidence only).

## References
""" + REFS_COMMON + """- `docs/plan/02-definition-of-ready-done.md` - Story DoD design sign-off item.
- `docs/plan/30-release-roadmap.md` section 9.4 - R5 quality gates.
""")
