# -*- coding: utf-8 -*-
"""E47 — Accessibility conformance (WCAG 2.2 AA). Part 1: shared helpers + epic."""

T = []


def t(key, kind, title, labels, component, sprint, priority, perspective, risk,
      estimate, parent, blocked_by, body, phase="P5 Collaboration & Polish",
      milestone="R5 Hardening / GA"):
    T.append(dict(key=key, kind=kind, title=title, labels=labels, component=component,
                  phase=phase, sprint=sprint, priority=priority, perspective=perspective,
                  risk=risk, estimate=estimate, parent=parent, blocked_by=blocked_by,
                  milestone=milestone, body=body))


REFS_COMMON = """- `docs/plan/05-accessibility-standard.md` - the binding standard (sections cited per ticket).
- `docs/plan/30-release-roadmap.md` section 9 - R5 Hardening / GA scope, exit criteria and quality gates.
- `docs/plan/03-testing-strategy.md` - test pyramid, axe/Lighthouse/keyboard-E2E cadence.
- `docs/plan/06-performance-and-load-standard.md` - frame/latency budgets the a11y layers must not violate.
- `docs/plan/14-screens-catalogue.md` - 149 SCR-* entries, each with an **A11y** and **Design sign-off acceptance checklist** block.
- `docs/plan/15-component-catalogue.md` section 0.3 - cross-cutting component rules 3-7 (colour-never-alone, keyboard contract, motion pair, test baseline).
- `docs/plan/02-definition-of-ready-done.md` - DoR/DoD gates; a11y is default-on for any UI ticket.
"""

EPIC_BODY = """## Context
R5 exists to convert "we believe it is accessible" into "we can evidence WCAG 2.2 AA conformance, per screen, with a signed-off report" (`docs/plan/30-release-roadmap.md` section 9.1 goal 2, section 9.3 exit criterion 2). Accessibility has been built in from Sprint 01 - `docs/plan/05-accessibility-standard.md` is referenced by every screen, component and design ticket; E05 shipped contrast-linted tokens, E10 shipped the single global hotkey layer and the SkipLink (CMP-085), E11 shipped the chart DOM mirror and data cursor. E47 is **not** a retrofit epic: it is the audit-remediate-evidence epic that proves the built system actually meets the standard across all 149 screens in `docs/plan/14-screens-catalogue.md` and all 238 components in `docs/plan/15-component-catalogue.md`, closes every finding, and publishes a VPAT-shaped conformance report.

The highest-risk surfaces are the ones the standard itself flags (`05-accessibility-standard.md` section 6): WebGL canvases (chart engine, footprint grid, DOM liquidity heatmap, volume/delta/TPO profiles) and the rule node-graph editor. These cannot be made accessible by markup alone; they rely on the three mandatory layers - offscreen DOM mirror (6.1), throttled ARIA live regions (6.2) and "View as table" data alternatives (6.3) - plus the canvas-semantics fallback (6.4). E47 verifies those layers end to end under real data density and real tick rates, not in a Storybook fixture.

Framing note from the standard section 1: CandleViewer is an internal tool with no external legal AA mandate. The AA bar is a deliberate owner decision - keyboard-first operation is a *trading speed* and RSI-risk requirement, and the owner may develop vision/motor conditions over the tool's lifetime. Accessibility findings are therefore triaged on the normal defect bar, never waived as "internal tool, does not matter".

## Scope / Deliverables
**In scope**
- A repeatable automated audit harness covering every SCR-* screen: axe-core (zero new serious/critical), Lighthouse Accessibility >= 95 on tracked top-level screens, accessibility-tree/landmark snapshots, keyboard-only E2E task script, motion/flash luminance audit (`05-accessibility-standard.md` section 9.1-9.6) - E47-T01, E47-T03, E47-T04, E47-T05.
- Full colour verification: the dark, light, high-contrast and three CVD-safe palettes (deuteranopia, protanopia, tritanopia, per SCR-116) validated against **every order-flow encoding** - footprint delta/imbalance, heatmap bid/ask gradient, CVD sign, profile bars, big-trade bubbles, P&L, order status, LIVE/DEMO badge (`05-accessibility-standard.md` sections 4 and 5) - E47-T02, E47-S04.
- Remediation of every finding, grouped by surface: chart canvas surfaces (E47-S01), order-flow canvases and the DOM ladder (E47-S02), both rule editors (E47-S03), non-canvas chrome/settings/admin/auth/journal (E47-S05), trading surfaces and destructive-action confirm gates (E47-S06).
- Screen-reader test scripts and executed manual passes against the pinned section 8.1 coverage matrix (NVDA/Electron P0, JAWS P1, VoiceOver P1 pre-GA) - E47-Q02, E47-Q03.
- Promotion of every a11y gate to a **required check** on `main`, with a findings burn-down dashboard - E47-T06.
- A published, VPAT-shaped accessibility conformance report plus an in-app accessibility statement linked from SCR-117 - E47-T07.
- An ADR recording the canvas-accessibility conformance strategy and every owner-accepted exception with its compensating control - E47-T08.

**Out of scope**
- Any Android/mobile screen reader (TalkBack) - locked out-of-scope decision, `docs/plan/00-planning-brief.md`.
- Safari-direct or non-Electron browser conformance - `05-accessibility-standard.md` section 8.1 note; Chromium-headless is a CI feedback target only.
- Building *new* product features or screens; E47 only changes behaviour where it is non-conformant. New-screen work belongs to its owning epic.
- Performance optimisation beyond keeping the a11y layers inside budget - that is E46.
- General design polish, copy review and non-a11y defect burn-down - that is E49.
- Procuring an external third-party accessibility certification.

## Acceptance criteria
```gherkin
Scenario: Per-screen conformance evidence exists
  Given the GA release candidate build
  When the conformance report is generated
  Then every one of the 149 SCR-* screens has a row with axe status, Lighthouse
    score, keyboard-task result and screen-reader pass date
  And no row is blank or marked "not assessed"

Scenario: No unresolved Level A or AA failure
  Given the findings register at the R5 exit gate
  Then every Level A/AA failure is either fixed and re-verified, or recorded as
    an Owner-accepted exception with a written compensating control, an owner
    and an expiry date
  And the count of unresolved, unaccepted A/AA failures is zero

Scenario: Gates are enforced, not advisory
  Given a pull request that introduces a serious axe violation on any screen
  When CI runs
  Then the required a11y check fails and the pull request cannot be merged

Scenario: Canvas surfaces are usable keyboard and screen-reader only
  Given a tester using NVDA on the Electron production build with no mouse
  When they perform the section 8.2 task script (switch symbol, place a limit
    order, read a footprint cell via the DOM mirror and via the table
    alternative, navigate the DOM ladder, edit a rule in both editors)
  Then every task completes
  And the DOM-mirror values match the table-alternative values for the same cell

Scenario: Failure path - announcement flooding
  Given a symbol streaming at 50 trades per second with announcements enabled
  When the ambient live region updates
  Then announcements are coalesced to the configured cadence (default one per 2s
    per field) presenting the latest value
  And the screen reader never queues a backlog of stale intermediate values
```

## Technical notes / design
Three-phase shape across S23-S25:
1. **S23 Audit** - stand up the harness (E47-T01), generate the *complete* findings register mechanically, run the colour matrix (E47-T02), triage findings into the remediation stories. Findings live in `docs/a11y/findings.csv` with columns `{screen, component, wcag_sc, level, severity, owner_ticket, status}`; every row must reach `fixed` or `accepted`.
2. **S24 Remediate** - the six remediation stories run in parallel by surface, each owning its slice of the register. Canvas work (E47-S01, E47-S02) is the long pole and starts first.
3. **S25 Evidence and lock** - re-run the full harness on the remediated build, execute the manual SR passes, promote gates to required checks (E47-T06), publish the report (E47-T07), design QA and QA sign-off.

Severity mapping (from `05-accessibility-standard.md` section 8.2 item 5): a section 8.2 task that cannot be completed keyboard+SR-only on a screen is **P0** for that screen; awkward-but-completable is P1/P2 on the normal triage bar.

## Test plan
Rolled up from children: axe-core + Lighthouse + accessibility-tree snapshots per screen (E47-T01), contrast/CVD matrix (E47-T02), keyboard-only Playwright suite driving the section 8.2 task script (E47-T03), motion/flash luminance audit (E47-T04), focus-order/landmark snapshot diffs (E47-T05), manual NVDA/JAWS/VoiceOver passes (E47-Q02), exploratory keyboard-only charter (E47-Q03), regression pack (E47-Q04), DOM-mirror/live-region overhead benchmark (E47-Q05).

## Security notes
Low but non-zero surface (`docs/plan/04-security-program.md`): (a) the offscreen DOM mirror materialises trading data in the DOM where a compromised renderer script could read it - same data classification as the visible canvas, no new classification, but it must respect the same RBAC scoping so a Viewer's mirror never contains data their role cannot see; (b) live-region announcements must never read secrets (API-key fragments, TOTP codes, session tokens); (c) accessibility accommodations must never weaken a safety gate - the keyboard path to "flatten all" or to arming 1-click trading must traverse the same confirm policy (US-SET-003) as the mouse path. Covered by E47-X01 (STRIDE) and E47-X02 (abuse cases and review). The published conformance report is an externally-shaped artifact and must not leak internal hostnames, account ids, or screenshots containing live positions.

## Accessibility notes
This epic *is* the accessibility work. Target: WCAG 2.2 Level AA across all screens, with the section 1 AAA stretch goals (>= 7:1 for buy/sell primary actions and the LIVE/DEMO badge) attempted where the palette allows. Conformance is evidenced per screen, not asserted globally.

## Performance notes
The a11y layers sit inside the frame budget, not beside it (`docs/plan/06-performance-and-load-standard.md` budgets 1, 3 and 14): the DOM mirror is windowed to <= 200 rows (`26-chart-engine-design.md` section 12), live-region updates are throttled to one announcement per 250 ms for the data cursor and one per 2 s per ambient field, and enabling "prefer table alternatives" must not regress p95 frame time beyond 16.6 ms. E47-Q05 measures this; any regression is handed to E46.

## Observability
- Metric `a11y_findings_open{level,severity}` published to the burn-down dashboard (E47-T06).
- CI artifacts per run: axe JSON, Lighthouse JSON, accessibility-tree snapshots, motion-audit frame captures - retained per release for audit.
- Analytics event `a11y.preference_changed {key,value}` (already specified on SCR-117) aggregated so we can see which accommodations are actually used.

## Definition of Done
- [ ] Every child ticket Done or explicitly descoped with a recorded disposition.
- [ ] Findings register fully resolved: zero unresolved, unaccepted Level A/AA failures.
- [ ] axe-core, Lighthouse, keyboard-E2E, motion-audit and focus-snapshot gates are required checks on `main`.
- [ ] Manual screen-reader passes executed and signed off per the section 8.1 matrix (NVDA full, JAWS full, VoiceOver full pre-GA).
- [ ] VPAT-shaped conformance report published and linked from the in-app accessibility statement on SCR-117.
- [ ] ADR recorded for the canvas-accessibility conformance strategy and all accepted exceptions.
- [ ] Design sign-off (Accessibility role plus CDO delegate) and QA sign-off recorded.
- [ ] `docs/plan/05-accessibility-standard.md` reconciled with shipped behaviour where they diverged.
- [ ] Demoed to the Owner: a full section 8.2 task script run, keyboard and NVDA only.

## Dependencies
- **E44 Live-enablement gating** (roadmap dependency graph `E44 --> E47`): the Demo/Live environment surfaces and confirm gates must be final before their a11y contract is frozen.
- **E43 Security hardening**: confirm-policy and step-up-auth flows must be settled before their keyboard/SR paths are certified.
- **E05 Design system v0**: token layer, contrast linter and component a11y contracts are the foundation being audited.
- **E10 App shell**: landmarks, SkipLink (CMP-085) and the global hotkey layer (US-SET-002).
- **E11 Chart engine core**: DOM mirror and data cursor API (`26-chart-engine-design.md` section 12).
- **E18 / E19 / E21**: footprint, profiles, DOM ladder and heatmap surfaces being audited.
- **E36 / E37**: rule form editor and node-graph editor.
- E47 blocks **E49** (defect burn-down and design-QA sweep) per the roadmap dependency graph.

## Branch
`feat/e47-a11y-conformance` (umbrella); children use `feat/e47-<short>` / `fix/e47-<short>`. PR size guidance: remediation PRs stay <= 400 LOC and are grouped by screen family so each is reviewable by the owning team plus the Accessibility role.

## Children and dependency graph
```mermaid
graph TD
    D01[E47-D01 UX research: SR and keyboard sessions]
    D02[E47-D02 High-contrast and CVD palettes]
    D03[E47-D03 Accessible-alternative patterns hi-fi]
    D04[E47-D04 Motion audit and motion-reduce pairs]
    D05[E47-D05 A11y design review and sign-off]
    D06[E47-D06 Handoff and design-system contribution]
    D07[E47-D07 Design QA of remediated screens]
    K01[E47-K01 Spike: audit harness at 149-screen scale]
    T01[E47-T01 Automated audit harness]
    T02[E47-T02 Contrast and CVD token matrix]
    T03[E47-T03 Keyboard-only E2E task script]
    T04[E47-T04 Motion and flash audit script]
    T05[E47-T05 Focus-order and landmark snapshots]
    T06[E47-T06 Promote gates to required checks]
    T07[E47-T07 Conformance report and statement]
    T08[E47-T08 ADR: canvas a11y conformance strategy]
    S01[E47-S01 Chart canvas remediation]
    S02[E47-S02 Order-flow canvas and DOM ladder remediation]
    S03[E47-S03 Rule editors remediation]
    S04[E47-S04 High-contrast and CVD theme conformance]
    S05[E47-S05 Chrome settings admin auth journal remediation]
    S06[E47-S06 Trading surfaces and confirm-gate remediation]
    Q01[E47-Q01 Black-box a11y test plan]
    Q02[E47-Q02 Manual screen-reader passes]
    Q03[E47-Q03 Keyboard-only exploratory charter]
    Q04[E47-Q04 Regression pack and QA sign-off]
    Q05[E47-Q05 A11y-layer overhead benchmark]
    X01[E47-X01 STRIDE threat model]
    X02[E47-X02 Abuse cases and security review]

    D01 --> D02
    D01 --> D03
    D02 --> D05
    D03 --> D05
    D04 --> D05
    D05 --> D06
    D02 --> S04
    D03 --> S01
    D03 --> S02
    D03 --> S03
    D06 --> S05
    D06 --> S06
    K01 --> T01
    T01 --> T03
    T01 --> T05
    T01 --> S01
    T01 --> S02
    T01 --> S03
    T01 --> S05
    T01 --> S06
    T02 --> S04
    T04 --> S01
    T08 --> S01
    S01 --> S02
    T03 --> T06
    T04 --> T06
    T05 --> T06
    S01 --> T07
    S02 --> T07
    S03 --> T07
    S04 --> T07
    S05 --> T07
    S06 --> T07
    T01 --> Q01
    Q01 --> Q02
    Q01 --> Q03
    S01 --> Q02
    S02 --> Q02
    S03 --> Q02
    Q02 --> Q04
    Q03 --> Q04
    T06 --> Q04
    T07 --> Q04
    D07 --> Q04
    S01 --> Q05
    S02 --> Q05
    X01 --> X02
    S06 --> X02
    S05 --> D07
    S06 --> D07
```

## Risks
| Risk | Mitigation |
|---|---|
| **R2 Render performance** - DOM mirror, live regions and table alternatives add per-frame main-thread work on the hottest surfaces | Windowed mirror (<= 200 rows), throttled announcements, benchmark gate E47-Q05; regressions handed to E46 |
| **R8 Browser/GPU compat** - high-contrast and forced-colors modes can break canvas rendering assumptions | Explicit forced-colors test case in E47-S04; canvas falls back to the token-driven palette and is never system-colour-dependent |
| **R5 Scope** - "audit every screen" is 149 screens times 6 palettes; manual effort explodes | The audit is mechanised first (E47-T01/T02); manual passes are limited to the section 8.1 pinned matrix and the section 8.2 fixed task script |
| **R10 Key-person** - a single Accessibility role signs off everything | The frontend a11y champion is a named delegate (section 8.3); test scripts and the report generator are checked in, not tribal |
| **Late discovery** - an architectural non-conformance found in S24 with no time to fix | The S23 audit is exhaustive and mechanical *before* remediation starts; anything architectural becomes an Owner-accepted exception with a compensating control and a post-GA ticket, per section 9.3 exit criterion 2 |

## References
""" + REFS_COMMON + """- `docs/plan/26-chart-engine-design.md` section 12 - engine accessibility layer (focusable canvas, data cursor, DOM mirror), section 13 test matrix.
- `docs/plan/16-design-system-brief.md` - tokens, theming, motion, density.
- `docs/plan/18-traceability-matrix.md` - US -> SCR -> CMP mapping used to scope the audit.
- `docs/plan/07-release-and-prr.md` - PRR/GA checklist gates that consume this epic's evidence.
- `docs/plan/32-risk-register.md` - R2, R8, R10.
"""


def build_epic():
    t("E47", "Epic", "Accessibility conformance (WCAG 2.2 AA)",
      ["type/feature", "area/design-system", "priority/p1", "a11y", "design", "qa",
       "security", "perf"],
      "cross-cutting", "Sprint 23", "P1 High", "Product", "R2 Render performance",
      87, None,
      ["E44", "E43", "E05", "E10", "E11", "E18", "E19", "E21", "E36", "E37"],
      EPIC_BODY)
