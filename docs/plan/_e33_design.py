# -*- coding: utf-8 -*-
"""E33 design tickets D01..D07 (perspective Product, design labels)."""

from _e33_epic import REFS_COMMON, MS, PH

TICKETS = []


def add(**kw):
    TICKETS.append(kw)


DES_REFS = REFS_COMMON + """
- `docs/plan/16-design-system-brief.md` (tokens, theming, motion, density, a11y)
- `docs/plan/13-user-flows.md` F8 (order placement) and F9 (algo/bracket management)
- `docs/plan/17-ux-diagrams.md` (journey maps, state diagrams)
- `docs/plan/02-definition-of-ready-done.md` §3.1 design-ready gate (design Done ≥2 sprints before the consuming FE story)"""

# ---------------------------------------------------------------- D01
add(
    key="E33-D01",
    kind="Task",
    title="UX research: how traders configure and trust an emulated algorithm",
    labels=["type/research", "area/oms-execution", "priority/p1", "design", "ux-research"],
    component="web",
    phase=PH,
    sprint="Sprint 14",
    priority="P1 High",
    perspective="Product",
    risk="R11 Alert reliability",
    estimate=3,
    parent="E33",
    blocked_by=[],
    milestone=MS,
    body="""## Context
E33 introduces four order types that **do not exist at the exchange**. The product promises behaviour that only holds while CandleViewer's backend is alive, which is a fundamentally different trust contract from a native order. Every screen in SCR-066..070 therefore carries an honesty burden that no other trading screen has, and `11-user-stories.md` §18 NFRs repeat it: iceberg "must be labelled (app-managed) everywhere it appears"; the OCO builder must explain race resolution and residual risk; the monitor panel must say that algos suspend while the backend reconnects and native stops still protect.

Nobody has tested whether that message actually lands. This research answers: do traders understand what "emulated" costs them, what mental model do they bring to slicing/pegging configuration, which parameters do they actually tune, and what do they expect to happen when the app goes away mid-algo?

## Scope / Deliverables
- Moderated sessions with the Owner and 4–6 comparable active perpetual-futures traders (recruit from the existing research panel; sessions ≤ 60 min).
- Stimuli: competitor iceberg/TWAP/chase builders, a paper prototype of the SCR-066..069 parameter sets, and a scripted "the backend just died mid-TWAP" scenario.
- Research questions:
  1. Which parameters do traders set themselves versus expect a sensible default for (slice count vs duration; visible size vs show-ratio; peg offset vs max chase distance)?
  2. How do they interpret "emulated / app-managed"? Does the phrase communicate residual risk, or do they read it as a technicality?
  3. What do they expect on disconnect — cancel everything, freeze, or continue? (The system's answer is `freeze`; the research tests whether that matches expectation and how to phrase it if it does not.)
  4. What do they need to see in a monitor panel to feel that "nothing is running invisibly" (US-ALGO-010)?
  5. What is the minimum acceptable pre-submit information — schedule preview, projected request rate, slippage estimate?
- Deliverables: a findings report in `docs/research/` with verbatim quotes, a prioritised list of design implications, recommended default parameter values per strategy, and the agreed wording for the emulation caveat and the disconnect message (which becomes binding copy for E33-D02/D03).

## Out of scope
Visual design (D02/D03). Testing built software (that is E33-Q06 exploratory + the a11y audit). Rule-engine or bracket UX (E32/E35–E37).

## Acceptance criteria
```gherkin
Scenario: Findings answer every research question
  Given the sessions are complete
  Then the report answers all five research questions with evidence, not opinion,
  and each answer names the screens it affects

Scenario: Emulation wording decided
  Given participants read candidate phrasings of the emulation caveat
  Then one phrasing per strategy is chosen with evidence that participants correctly restated
  the residual risk in their own words, and that phrasing is recorded as binding copy

Scenario: Defaults recommended (edge)
  Given disagreement between participants on a parameter default
  Then the report states the disagreement, recommends a default with its rationale,
  and flags the parameter as one to revisit after the R3 soak
```

## Technical notes / design
Use the existing research protocol and consent process. Sessions recorded with consent; recordings stored per the research data-handling rules in `04-security-program.md`. Do not demo real accounts — use demo credentials and synthetic positions.

## Test plan
N/A — research. Validity controls: at least one participant unfamiliar with CandleViewer to catch jargon; the disconnect scenario is run *before* any explanation is given, so comprehension is measured rather than taught.

## Security notes
Participant data is PII: recordings, notes and recruiting records follow the research retention policy; no participant sees live account data or keys. Sessions run on demo only.

## Accessibility notes
Recruit at least one participant who uses keyboard-primary interaction or magnification, so the monitor-panel density findings are not sighted-mouse-only.

## Performance notes
N/A.

## Observability
N/A.

## Definition of Done
- [ ] ≥ 5 sessions completed and synthesised.
- [ ] Findings report merged to `docs/research/` and linked from this ticket.
- [ ] Binding copy for the emulation caveat and disconnect message agreed and recorded.
- [ ] Recommended defaults per strategy listed and handed to E33-D02/D03 and to E33-T01's config defaults.
- [ ] Reviewed with the Chief Design Officer and the OMS tech lead.
- [ ] **Sign-off:** CDO + Owner accept the findings as the basis for E33-D02/D03.

## Dependencies
None blocking. Informed by E30's order-ticket research if already complete.

## Branch
`design/e33-algo-research` (docs only).

## References
""" + DES_REFS,
)

# ---------------------------------------------------------------- D02
add(
    key="E33-D02",
    kind="Task",
    title="Wireframe to hi-fi: TWAP, iceberg and chase builders (SCR-066, 067, 068)",
    labels=["type/design", "area/oms-execution", "priority/p1", "design"],
    component="web",
    phase=PH,
    sprint="Sprint 15",
    priority="P1 High",
    perspective="Product",
    risk="R11 Alert reliability",
    estimate=5,
    parent="E33",
    blocked_by=["E33-D01"],
    milestone=MS,
    body="""## Context
Three of the four builders are parameter-heavy modals whose screens-catalogue entries already fix their content, validation messages and states (`14-screens-catalogue.md` SCR-066, SCR-067, SCR-068). This ticket takes them from wireframe to hi-fi in Figma using the E33-D01 findings and the recommended defaults, and produces the state coverage each entry's sign-off checklist demands.

## Scope / Deliverables
- **SCR-066 TWAP builder**: total qty, duration, slice count/interval, price limit (max slippage), randomisation, participation cap, limit-vs-market slices, price-band guard, disconnect behaviour; a **schedule preview table** (slice #, planned time, qty); states configured · running (progress, filled/remaining, average price, slices done) · paused (auto-paused on disconnect, with the banner) · degraded · completed · cancelled · failed; the "algo pauses if the backend disconnects; native stops still protect" message; cancel and cancel-and-flatten paths with confirmation.
- **SCR-067 Iceberg builder**: total qty, visible qty, refresh behaviour, price offset/peg, max show-ratio; "emulated client-side — Bybit has no native iceberg" stated prominently; **projected request rate** shown; running state with slices done/remaining; residual-risk note if the backend stops mid-algo; the validation messages drawn verbatim ("Visible size must be at least the minimum lot and no more than half the total.").
- **SCR-068 Chase-limit builder**: peg source as a radio group (best bid / best ask / mid) plus a signed tick offset with the resulting price previewed in text; re-peg threshold; max chase distance from the arrival price; max repricings; **fall-back-to-market as opt-in with its slippage risk stated**; timeout; the rate-limit estimate ("≈ 12 requests/min — within your per-account budget") and the refusal state when a configuration exceeds the budget; states running (current peg, repricings used, distance travelled) · limit reached · fell back to market · cancelled.
- Shared **`AlgoBuilderShell`** pattern drawn once: title, emulation notice, CMP-158 SafetyInvariantNotice, projected-rate chip (CMP-130), validation summary, submit/cancel — so honesty affordances are structural, not per-screen discipline.
- Light and dark, both densities, at the reference 4 K and 1 080 p displays.
- Redlines for spacing, type, tokens and every validation message, plus a state matrix per screen.

## Out of scope
SCR-069 OCO builder and SCR-070 monitor (D03). Motion (D04). A11y annotation (D05 — though obvious issues are fixed here). Scaled/ladder builder SCR-065 (E32).

## Acceptance criteria
```gherkin
Scenario: Every state in the catalogue is drawn
  Given the sign-off checklists in 14-screens-catalogue.md for SCR-066, SCR-067 and SCR-068
  Then every checklist item has a corresponding frame, and the checklist is ticked in the ticket

Scenario: Emulation and residual risk are structural
  Given any of the three builders
  Then the emulation caveat and the native-stop floor appear as persistent text blocks in the
  shared shell rather than as per-screen tooltips, in every state including running and failed

Scenario: Validation messages are exact (edge)
  Given the validation rules in the catalogue entries
  Then each message is drawn with the exact wording engineering must implement,
  including the numeric interpolation points

Scenario: Budget refusal is designed, not an afterthought (edge)
  Given a chase configuration projected to exceed the account rate budget
  Then a refusal state is drawn that names the projected and the allowed rate and offers the
  nearest acceptable configuration
```

## Technical notes / design
Use only existing catalogue components (CMP-008, 043, 047, 100, 101, 118, 130, 158, 227); any new pattern goes through E33-D04 as a design-system contribution rather than a one-off. Numbers shown in examples must be plausible BTCUSDT/ETHUSDT values honouring real `tickSize`/`qtyStep`.

## Test plan
Design review with the OMS tech lead to confirm every parameter maps to a real field of `AlgoSpec` (`22-api-openapi.yaml`) and `24-internal-schemas.md` §10.3–§10.5 — a drawn control with no backing field is a defect found here, not in code review.

## Security notes
The designs must not invite unsafe configuration: fall-back-to-market is opt-in, max-chase-distance has no "unlimited" affordance, and slice counts are bounded by the drawn validation. The arm/lock and confirmation policy from E30 are shown, not re-invented.

## Accessibility notes
Contrast AA on all states incl. degraded; focus order drawn; every field labelled with units; the emulation caveat is body text, not a tooltip; the peg selector is a radio group, not a segmented control that traps screen readers. Full annotation lands in D05.

## Performance notes
Designs must respect the 2 Hz progress-update cadence (no animation implying sub-second precision) — see SCR-066's performance note.

## Observability
The analytics events `algo.twap_previewed` and `algo.iceberg_previewed` are attached to the drawn preview affordances so instrumentation is specified at design time.

## Definition of Done
- [ ] Figma file complete: wireframes → hi-fi, all states, light/dark, both densities.
- [ ] Every catalogue sign-off checklist item ticked with a linked frame.
- [ ] Redlines and a state matrix published.
- [ ] Reviewed by the OMS tech lead for field-level feasibility.
- [ ] **Sign-off:** CDO approves; ticket Status Done ≥ 2 sprints before E33-S05 (Sprint 18) — i.e. by end of Sprint 16 at the latest.

## Dependencies
E33-D01 (findings, binding copy, recommended defaults). E30's order-ticket design for the arm/lock and confirmation patterns these modals sit inside.

## Branch
`design/e33-algo-builders` (Figma + docs).

## References
""" + DES_REFS,
)

# ---------------------------------------------------------------- D03
add(
    key="E33-D03",
    kind="Task",
    title="Hi-fi: OCO builder (SCR-069) and algo monitor panel (SCR-070)",
    labels=["type/design", "area/oms-execution", "priority/p1", "design"],
    component="web",
    phase=PH,
    sprint="Sprint 15",
    priority="P1 High",
    perspective="Product",
    risk="R11 Alert reliability",
    estimate=5,
    parent="E33",
    blocked_by=["E33-D01"],
    milestone=MS,
    body="""## Context
SCR-069 and SCR-070 are the two screens where emulation stops being a configuration detail and becomes a risk conversation. The OCO builder must explain **race resolution** and what happens if the app is offline when a leg fills; the monitor panel is the single place that discharges US-ALGO-010's promise that "nothing runs invisibly", including the degraded state in which algos are suspended and only native stops protect.

## Scope / Deliverables
- **SCR-069 Emulated OCO / bracket builder** — the **OCO half** (E32 owns the bracket half of the same modal, and this design must compose with it):
  - Both variants drawn: entry + OCO exit pair, and a standalone OCO on an existing position.
  - "Emulated — Bybit's API has no OCO" stated prominently as text.
  - Race-resolution behaviour explained as a paragraph (the losing leg is cancelled/reduced on the fill notice).
  - **Residual-risk state** drawn: app offline during a fill — what happened and what the user must do.
  - The mandatory native SL floor shown as always present and non-removable.
  - The "use native attached TP/SL instead" guidance for the plain TP+SL case, including the refusal state.
  - Validation messages: legs on opposite sides of the mark; quantities matching the position.
- **SCR-070 Algo monitor panel** (standalone panel and the Algos tab of SCR-063):
  - Table with id, type, symbol, account, type-specific progress, filled/remaining, average price, next-action countdown, controls.
  - Every algo type rendered with its own progress metric (TWAP slices, chase repricings + distance, iceberg slices, OCO leg states).
  - Rows for running · paused · degraded · completed · failed-with-reason · **halted by risk control** · orphaned (with adopt/cancel).
  - Bulk "pause all" and "cancel all" with a confirmation restating the count, and the per-item result view.
  - The degraded banner explaining suspension during backend reconnection and that native stops still protect.
  - Empty state; filter bar (account / symbol / kind / status); "last reconciled" indicator.
  - A 100-row density frame proving the layout at scale.
- Redlines, state matrix, and the exact copy for every banner and confirmation.

## Out of scope
SCR-066/067/068 (D02). Motion (D04). A11y annotation (D05). The bracket half of SCR-069 and SCR-063's other tabs (E32/E29).

## Acceptance criteria
```gherkin
Scenario: Catalogue checklists satisfied
  Given the sign-off checklists for SCR-069 and SCR-070
  Then every item has a linked frame and is ticked in the ticket

Scenario: Residual risk is explicit
  Given the OCO builder
  Then the offline-during-fill residual-risk state is drawn as a persistent note with a clear
  statement of what the user must do, not as a transient toast

Scenario: Nothing runs invisibly
  Given the monitor panel with one algo of each kind plus one orphan
  Then each row communicates its type-specific progress and next action, the orphan offers
  adopt and cancel, and the last-reconciled time is visible

Scenario: Degraded state (failure)
  Given the backend is reconnecting
  Then a status banner explains that algos are suspended and native stops still protect,
  rows are visibly stale, and controls that cannot be honoured are drawn disabled with a reason

Scenario: Bulk action safety (edge)
  Given 40 running algos and a cancel-all action
  Then the confirmation restates the count and the consequence per algo type,
  and the per-item result view is drawn including partial failure
```

## Technical notes / design
Components: CMP-023, CMP-043, CMP-049, CMP-055, CMP-100, CMP-101, CMP-118, CMP-119, CMP-123, CMP-158, CMP-227. Progress must be expressible as text, so the design cannot depend on a bar alone. Countdowns are drawn at 1 s granularity consistent with a single shared ticker.

## Test plan
Review with the OMS tech lead to confirm every drawn field exists in the `AlgoRun` projection (E33-T02) and every control maps to a real verb (pause / resume / cancel / cancel-and-flatten / adopt / cancel-orphan).

## Security notes
Destructive bulk actions need confirmations proportionate to their blast radius, and `viewer` variants are drawn with controls **absent** rather than disabled-with-tooltip, so the UI does not advertise capabilities the role lacks. The adopt action is drawn as the deliberate, owner/manager-only action it is.

## Accessibility notes
The monitor is a real table with headers; progress text-first; the degraded banner is `role="status"`; each control's accessible name includes its target algo and effect; the OCO residual-risk warning is `role="note"` and always visible. Bulk confirmations are `role="alertdialog"` restating counts. Full annotation in D05.

## Performance notes
The 100-row frame must be achievable inside SCR-070's 3 ms-per-frame scripting budget: virtualised rows, no per-row timers, no per-row animation.

## Observability
Audit events per control are annotated on the frames (`algo.cancelled`, `algo.paused`, `algo.orphan_adopted`), satisfying the catalogue checklist item "every control confirmed to emit an audit event".

## Definition of Done
- [ ] Figma complete: both screens, every state, light/dark, both densities, 100-row density frame.
- [ ] Catalogue checklists ticked with linked frames.
- [ ] Redlines, state matrix and exact copy published.
- [ ] Reviewed by the OMS tech lead for projection/verb feasibility.
- [ ] **Sign-off:** CDO approves; Done ≥ 2 sprints before E33-S06 (Sprint 18).

## Dependencies
E33-D01 (findings and binding copy). E29's SCR-063 tab shell design. E32's bracket design for SCR-069 composition.

## Branch
`design/e33-oco-monitor`.

## References
""" + DES_REFS,
)

# ---------------------------------------------------------------- D04
add(
    key="E33-D04",
    kind="Task",
    title="Design-system contribution and motion spec for emulated-algo surfaces",
    labels=["type/design", "area/oms-execution", "priority/p2", "design"],
    component="web",
    phase=PH,
    sprint="Sprint 16",
    priority="P2 Medium",
    perspective="Product",
    risk="R5 Scope",
    estimate=3,
    parent="E33",
    blocked_by=["E33-D02", "E33-D03"],
    milestone=MS,
    body="""## Context
D02 and D03 introduce patterns that must not remain E33-local: the shared `AlgoBuilderShell`, the type-specific progress presentation on CMP-118 AlgoProgressCard, the degraded/halted row treatments, and the "emulated" affordance built from CMP-227 EstimatedBadge + CMP-158 SafetyInvariantNotice. `02-definition-of-ready-done.md` §3.1 requires that "any new component has a design-system entry, not an ad hoc one-off". This ticket lands those contributions and specifies the motion rules for a surface whose data arrives at 2 Hz.

## Scope / Deliverables
- **CMP-118 AlgoProgressCard** extension: add `oco` to `algoType` (currently `twap|iceberg|chase|scaled`) with its leg-state presentation; specify the text-first progress string per kind ("60 %, 6 of 10 slices"; "repriced 7×, 3 ticks from arrival"); document the `emulated: true` invariant that the card never hides.
- **`AlgoBuilderShell`** added to `15-component-catalogue.md` as a molecule with props, states, a11y contract and Storybook story list.
- **Status treatments** added to the design system: `degraded`, `halted by risk control`, `orphaned` — token choices, iconography, and the rule that status is never colour-only.
- **Motion spec**: progress bars and countdowns animate at most at the 2 Hz data cadence with no easing that implies sub-second precision; state transitions (running → paused → degraded) cross-fade at 120 ms; the degraded banner enters without motion (it is a `role="status"` announcement, and motion competes with the announcement); all motion respects `prefers-reduced-motion` with a specified reduced variant.
- Token/spacing audit of the four builders and the monitor against `16-design-system-brief.md`, with any drift either justified or corrected.

## Out of scope
New screens. Behavioural design decisions (D02/D03). Implementation (S05/S06). Components owned by other epics (CMP-119 BracketEditor is E32's).

## Acceptance criteria
```gherkin
Scenario: Contributions are in the system, not in the epic
  Given the new patterns from D02 and D03
  Then AlgoBuilderShell and the three status treatments exist as catalogue entries with props,
  states, a11y contract and Storybook story lists, and CMP-118 documents the oco variant

Scenario: Motion respects the data cadence
  Given progress updates arriving at 2 Hz
  Then the motion spec forbids animation implying finer granularity, and specifies the exact
  durations and easings for state transitions

Scenario: Reduced motion (edge)
  Given prefers-reduced-motion is set
  Then every animation has a specified reduced variant that still communicates the state change
  without movement

Scenario: Token drift caught (edge)
  Given the audit of D02/D03 frames against the design-system brief
  Then every deviation is either corrected in the frames or recorded as a deliberate,
  justified exception in the catalogue entry
```

## Technical notes / design
Contributions follow the design-system team's intake process; entries are written in `15-component-catalogue.md`'s existing format (Tier · Purpose · Props · TypeScript interface · Data contract · A11y · Storybook).

## Test plan
Design-system review board acceptance. Storybook story lists are agreed here so E33-S05/S06's DoD checkboxes are unambiguous.

## Security notes
The `emulated: true` invariant on CMP-118 is a **safety-transparency control**, not a cosmetic prop: the catalogue entry must state that no consumer may set it false or hide the badge. Reviewed as such.

## Accessibility notes
Each new entry carries a full a11y contract (roles, accessible names, announcement politeness, contrast). The status treatments must be distinguishable in greyscale and in all three colour-vision simulations.

## Performance notes
Motion must not introduce per-row animation on SCR-070 — the 100-row case is the constraint (3 ms/frame scripting budget).

## Observability
N/A.

## Definition of Done
- [ ] `15-component-catalogue.md` updated with the new/extended entries.
- [ ] `16-design-system-brief.md` motion section updated with the algo cadence rules.
- [ ] Token audit complete with deviations resolved.
- [ ] Design-system review board approval recorded.
- [ ] **Sign-off:** CDO + design-system lead.

## Dependencies
E33-D02 and E33-D03 supply the patterns to systematise.

## Branch
`design/e33-ds-contrib`.

## References
""" + DES_REFS,
)

# ---------------------------------------------------------------- D05
add(
    key="E33-D05",
    kind="Task",
    title="Accessibility design review of the algo builders and monitor panel",
    labels=["type/design", "area/oms-execution", "priority/p1", "design", "a11y"],
    component="web",
    phase=PH,
    sprint="Sprint 16",
    priority="P1 High",
    perspective="Product",
    risk="None",
    estimate=2,
    parent="E33",
    blocked_by=["E33-D02", "E33-D03"],
    milestone=MS,
    body="""## Context
`05-accessibility-standard.md` sets WCAG 2.2 AA with no "internal tool" exception, and the SCR-066..070 catalogue entries each carry specific a11y requirements that are easy to lose in implementation: fields labelled *with units*, the emulation caveat as a paragraph rather than a tooltip, the TWAP schedule as a real table, the chase peg as a radio group with a text price preview, the OCO residual-risk warning as an always-visible `role="note"`, running states announcing refreshes politely at most once every 5 s, and the monitor's degraded banner as `role="status"` with controls whose accessible names include their target algo and effect.

This review annotates the D02/D03 designs so those requirements arrive as a spec, not as a bug report after E33-Q05.

## Scope / Deliverables
- Annotated a11y layer over every SCR-066..070 frame: semantic roles, heading structure, landmark/table semantics, focus order, focus-trap and restoration for each modal, accessible names for every control (including the "Cancel TWAP a_12 on BTCUSDT, Main" pattern), and the reading order of the emulation/residual-risk text relative to the fields it qualifies.
- Announcement policy: which changes are `polite`, which are `assertive` (validation failures and "halted by risk control"), and the 5 s politeness throttle for running-state refreshes.
- Keyboard maps: full operability of each builder and of the monitor table, including bulk actions and the orphan adopt/cancel row actions, with no mouse-only affordance anywhere.
- Contrast and non-colour-encoding verification for every status treatment (running / paused / degraded / halted / failed / orphaned) in light, dark, greyscale and the three colour-vision simulations.
- Target-size check (≥ 24 × 24 CSS px) across both densities, especially the dense monitor rows.
- A written a11y acceptance checklist that E33-Q05 executes verbatim against the built screens.

## Out of scope
Auditing built software (E33-Q05). Implementation. Chart-canvas a11y (E11/E31).

## Acceptance criteria
```gherkin
Scenario: Every screen is annotated
  Given SCR-066 through SCR-070
  Then each has a complete a11y annotation layer covering roles, names, focus order,
  announcements and keyboard operation

Scenario: No mouse-only path
  Given the keyboard map for each screen
  Then every action including bulk cancel-all and orphan adoption has a keyboard path,
  and each is demonstrated in the annotation

Scenario: Status is never colour-only (edge)
  Given each status treatment rendered in greyscale and the three colour-vision simulations
  Then every status remains distinguishable by glyph and text, and contrast meets AA in both themes

Scenario: Announcement throttle specified (edge)
  Given a running iceberg refreshing slices rapidly
  Then the annotation specifies a polite announcement at most once every five seconds,
  so a screen-reader user is informed without being flooded
```

## Technical notes / design
Follow the annotation conventions already used for the R3 trading screens (E30/E31) so implementers see one consistent format across the train.

## Test plan
The deliverable checklist is itself the test artefact for E33-Q05; each item must be objectively checkable (a named role, a named key, a measured ratio), never "is accessible".

## Security notes
Accessible names must not leak data a role cannot see: a `viewer`'s monitor row names must not include controls they lack, and no accessible name may expose another account's label to a manager without access.

## Accessibility notes
This ticket is the accessibility notes for the epic's UI; see Scope.

## Performance notes
Announcement throttling exists partly for performance: live-region churn at 2 Hz across 100 rows is both an a11y and a main-thread problem, so the annotation caps live-region updates to aggregate summaries rather than per-row messages.

## Observability
N/A.

## Definition of Done
- [ ] Annotation layer complete for SCR-066..070 and reviewed with the accessibility specialist.
- [ ] Keyboard maps and announcement policy published.
- [ ] Contrast/colour-vision verification recorded with measured ratios.
- [ ] The a11y acceptance checklist handed to E33-Q05 and referenced from E33-S05/S06.
- [ ] **Sign-off:** accessibility lead + CDO.

## Dependencies
E33-D02, E33-D03.

## Branch
`design/e33-a11y-review`.

## References
""" + DES_REFS,
)

# ---------------------------------------------------------------- D06
add(
    key="E33-D06",
    kind="Task",
    title="Design handoff package for the emulated-algo builders and monitor",
    labels=["type/design", "area/oms-execution", "priority/p1", "design", "handoff"],
    component="web",
    phase=PH,
    sprint="Sprint 16",
    priority="P1 High",
    perspective="Product",
    risk="None",
    estimate=2,
    parent="E33",
    blocked_by=["E33-D04", "E33-D05"],
    milestone=MS,
    body="""## Context
E33-S05 and E33-S06 are `blocked_by` this ticket: per `02-definition-of-ready-done.md` §3.1 no frontend screen work starts until its design is Done, and Done ≥ 2 sprints earlier. This is the package that makes the two stories buildable without a single clarifying question — and the artefact E33-D07 later checks the build against.

## Scope / Deliverables
- One consolidated handoff document + Figma dev-mode links covering SCR-066, SCR-067, SCR-068, SCR-069 (OCO half) and SCR-070.
- Per screen: redlines (spacing, type, tokens), the complete state matrix, **exact copy** for every label, helper, validation message, banner and confirmation (including the binding emulation and disconnect wording from E33-D01), the a11y annotation layer from E33-D05, and the motion spec from E33-D04.
- A **field → API mapping table**: every drawn control mapped to its `AlgoSpec` field (`22-api-openapi.yaml`) / `24-internal-schemas.md` §10 param and its validation source (instrument filter, account profile cap, rate budget), so no implementer has to infer a binding.
- A **control → verb → audit-event table** for SCR-070 (pause / resume / cancel / cancel-and-flatten / adopt / cancel-orphan → `POST /algos/...` → `algo.*` audit event).
- The Storybook story list agreed in E33-D04, restated as the checklist E33-S05/S06 must satisfy.
- Open-questions register: anything still undecided, with an owner and a date — empty at sign-off.
- A walkthrough session with the frontend engineers who will build S05/S06 and with QA (so E33-Q01's test plan is written from the same source).

## Out of scope
New design decisions (they belong to D02/D03 and must not be smuggled into handoff). Implementation. Design QA of the built result (D07).

## Acceptance criteria
```gherkin
Scenario: Buildable without questions
  Given the handoff package
  When a frontend engineer unfamiliar with the epic reads it
  Then they can build SCR-066..070 without asking a clarifying question,
  verified by the walkthrough producing zero unanswered questions

Scenario: Every control is bound
  Given the field-to-API mapping table
  Then every drawn control maps to a real AlgoSpec field or a real control verb,
  and every validation rule names its authoritative source

Scenario: Where documents disagree, handoff wins (edge)
  Given a discrepancy between the screens catalogue and the hi-fi designs
  Then the handoff states the resolution explicitly and flags it for E33-T03 to reconcile
  back into the plan docs

Scenario: Open questions closed (edge)
  Given the open-questions register at sign-off
  Then it is empty, or each remaining item is explicitly deferred with an owner, a date and a
  stated default behaviour engineering should implement meanwhile
```

## Technical notes / design
Publish as a single markdown document in `docs/plan/` adjacent to the screens catalogue with Figma dev-mode links, so it survives Figma access changes. Version it; S05/S06 cite the version they built against.

## Test plan
The walkthrough is the test: engineers and QA attempt to enumerate every state and every validation from the package alone. Any gap found is fixed before sign-off.

## Security notes
The package must carry the security-relevant UI rules verbatim so they cannot be dropped in implementation: arm/lock gating, confirmation policy per environment, `viewer` variants with controls absent, the non-removable native-SL notice, and the rule that client-side validation is never authoritative.

## Accessibility notes
The D05 annotation layer is embedded in the package, not linked as an optional extra, and the a11y acceptance checklist is restated as part of each story's DoD.

## Performance notes
The 2 Hz cadence, the virtualisation requirement and the single-ticker rule for SCR-070 are stated as implementation constraints in the package.

## Observability
The control → verb → audit-event table is the instrumentation spec; analytics events (`algo.*_previewed`, `algo.monitor_bulk_action`) are listed per surface.

## Definition of Done
- [ ] Package published and versioned; Figma dev-mode links live.
- [ ] Field→API and control→verb→audit tables complete and reviewed by the OMS tech lead.
- [ ] Walkthrough held with FE engineers and QA; zero unanswered questions recorded.
- [ ] Open-questions register empty or fully dispositioned.
- [ ] **Sign-off:** CDO + FE lead + QA lead; Status Done by end of Sprint 16 (≥ 2 sprints before Sprint 18).

## Dependencies
E33-D04 (design-system entries and motion), E33-D05 (a11y annotation). E33-T02's OpenAPI delta informs the field mapping — coordinate so the tables agree.

## Branch
`design/e33-handoff`.

## References
""" + DES_REFS,
)

# ---------------------------------------------------------------- D07
add(
    key="E33-D07",
    kind="Task",
    title="Design QA of the shipped algo builders and monitor panel",
    labels=["type/design", "area/oms-execution", "priority/p2", "design", "design-qa"],
    component="web",
    phase=PH,
    sprint="Sprint 18",
    priority="P2 Medium",
    perspective="Product",
    risk="None",
    estimate=2,
    parent="E33",
    blocked_by=["E33-S05", "E33-S06"],
    milestone=MS,
    body="""## Context
`02-definition-of-ready-done.md` §3.2 makes design QA default-on for net-new UI stories: the built screen is compared against the design spec (spacing, tokens, type, colour, states) by a designer or design-system-trained reviewer, and discrepancies are fixed or filed as bugs with a priority. E33-S05 and E33-S06 ship five net-new screens, several of which carry safety-transparency affordances whose absence would be a defect rather than a polish item.

## Scope / Deliverables
- Screen-by-screen comparison of the built SCR-066, SCR-067, SCR-068, SCR-069 (OCO half) and SCR-070 against the E33-D06 package version they were built from.
- Full **state sweep**: every state in the matrices — configured, running, paused, degraded, halted by risk control, completed, cancelled, failed-with-reason, orphaned, empty — in light and dark, both densities, at 4 K and 1 080 p.
- **Copy audit**: every label, helper, validation message and banner compared to the exact strings in the handoff, including the binding emulation and disconnect wording.
- **Safety-affordance audit** (treated as blocking, not cosmetic): the emulation caveat present as text in every state; CMP-158 SafetyInvariantNotice present and stating the non-removable native stop; CMP-227 EstimatedBadge present on every emulated surface; the degraded banner present and correctly worded; `viewer` variants showing no mutating controls.
- Motion check against the D04 spec including the `prefers-reduced-motion` variants.
- Findings list with severity; blocking items fixed before the stories close, non-blocking items filed as Bugs with `priority/*` and linked here.

## Out of scope
Functional testing (E33-Q01/Q02/Q06). A11y auditing (E33-Q05 — though a11y regressions noticed here are filed). Backend behaviour.

## Acceptance criteria
```gherkin
Scenario: Full state sweep performed
  Given the five shipped screens
  Then every state in the handoff matrices has been compared in both themes and densities,
  and the result is recorded per state

Scenario: Safety affordances present
  Given every emulated surface in every state
  Then the emulation caveat, the safety-invariant notice and the estimated badge are present
  and correctly worded; any absence is raised as a blocking defect, not a polish item

Scenario: Copy matches exactly (edge)
  Given the handoff's exact strings
  Then every shipped string matches, and any deviation is either corrected or recorded as a
  deliberate change with CDO approval and fed to E33-T03 for doc reconciliation

Scenario: Reduced motion honoured (edge)
  Given prefers-reduced-motion
  Then the reduced variants specified in D04 are what the build renders
```

## Technical notes / design
Review against the running demo environment, not Storybook alone — Storybook cannot show the degraded or halted states driven by real backend conditions; use the QA chaos fixtures (E33-Q04) to reach them.

## Test plan
N/A (this is the QA activity). Evidence is screenshots per state attached to the ticket.

## Security notes
The safety-affordance audit is a security control check: hiding or weakening the emulation/native-SL notices defeats a transparency control agreed in E33-X01's threat model, so such findings are blocking and are copied to the Security engineer.

## Accessibility notes
Any a11y deviation observed (missing focus ring, colour-only status, tooltip-only caveat) is filed immediately and cross-linked to E33-Q05 rather than deferred.

## Performance notes
Confirm no per-row animation crept into SCR-070 and that countdowns share a single ticker — visually verifiable by profiling the 100-row case.

## Observability
Confirm the analytics/audit affordances annotated in D06 actually fire from the built controls (spot-check via the audit log).

## Definition of Done
- [ ] All five screens swept across every state, theme and density; evidence attached.
- [ ] Blocking findings fixed and re-verified; non-blocking findings filed as Bugs with priorities and linked.
- [ ] Safety-affordance audit passed and countersigned by the Security engineer.
- [ ] **Sign-off:** CDO records design-QA acceptance on E33-S05 and E33-S06.

## Dependencies
E33-S05 and E33-S06 must be feature-complete; E33-Q04's chaos fixtures are used to reach degraded/halted states.

## Branch
N/A (review activity); fixes land on `fix/e33-design-qa-*` branches.

## References
""" + DES_REFS,
)
