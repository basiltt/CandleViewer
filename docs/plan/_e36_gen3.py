# -*- coding: utf-8 -*-
import json, os

PHASE = "P3 Drawing & Alerts"; MILE = "R3 Trading on demo"; AREA = "area/rule-engine"
T = []
def add(key, kind, title, labels, component, sprint, priority, perspective, risk, estimate, parent, blocked_by, body):
    T.append({"key": key, "kind": kind, "title": title, "labels": labels, "component": component,
        "phase": PHASE, "sprint": sprint, "priority": priority, "perspective": perspective,
        "risk": risk, "estimate": estimate, "parent": parent, "blocked_by": blocked_by,
        "milestone": MILE, "body": body.strip() + "\n"})

# ------------------------------------------------------------------ QA
add("E36-Q01", "Task", "Write the black-box test plan, fixtures and exploratory charters for the form editor",
    ["type/test", AREA, "priority/p0", "qa"], "web", "Sprint 16", "P0 Critical", "Test", "R5 Scope", 3,
    "E36", ["E36-D05", "E36-T01"], """
## Context
`docs/plan/03-testing-strategy.md` requires a black-box test plan per feature alongside the white-box review. E36 is a large surface (five screens, thirteen components) whose defects are subtle rather than loud: a dropped opaque region, a diagnostic anchored to the wrong row, an account visible that should not be. The plan is written before the code lands so the acceptance scenarios are testable by construction.

## Scope / Deliverables
- A black-box test plan covering SCR-080, SCR-081, SCR-083, SCR-088, SCR-089, organised by story group (authoring · validation · round-trip · templates · list · import/export) with, per case: preconditions, steps, expected result, and the plan doc clause it derives from.
- Boundary and negative cases enumerated explicitly: 0 conditions, 1 condition, 12 conditions, a nested any-of group, 0 actions, a duplicate action, a metric with no data source, an unknown identifier, an armed rule being edited, a concurrent save, an unreachable compile service, a quarantined IR, a newer-version import bundle, a 100-rule bundle, a 500-rule list.
- **Fixtures**: the shared `fixtures/rule-ir/*.json` corpus (≥30 documents, shared with E35 and E36-T01) plus recorded `GET /rules/vocabulary` responses (current, stale-ETag, malformed, missing-metric), recorded `POST /rules/validate` responses (valid, warnings-only, errors), a deliberately divergent form/graph pair for the mismatch path, and a 500-rule list fixture.
- **Exploratory charters** (session-based, 90 min each): "author the five most likely real rules and try to make the editor lose data"; "attack the boundary between form and graph representations"; "use the editor with the keyboard only and no mouse plugged in"; "import hostile bundles"; "operate the list while rule state changes underneath you".
- A per-story traceability table mapping every acceptance scenario in E36-S01..S06 to at least one test case, so a missing test is visible.
- Entry/exit criteria for QA sign-off and the bug-severity rubric to be used (blocker = data loss, wrong scope, or a11y Level A/AA failure).

## Out of scope
Writing the automation (E36-Q02), the a11y audit (E36-Q03), performance scripts (E36-Q04), security testing (E36-X02).

## Acceptance criteria
```gherkin
Scenario: Every acceptance scenario is covered
  Given the acceptance criteria of E36-S01 through E36-S06
  Then the traceability table maps each scenario to at least one test case with no gaps
Scenario: Fixtures are reusable, not one-off
  Given the IR corpus
  Then it is the same corpus E35 and packages/rule-editor-core use, so a change to the IR breaks all three at once
Scenario: A case is untestable as written (failure)
  Given an acceptance criterion with no observable outcome
  Then it is sent back to the story author and the story does not enter Ready until it is measurable
Scenario: Charters are time-boxed and reportable (edge)
  Then each charter states its mission, the areas in scope, the time box and the debrief format
```

## Technical notes / design
Plan lives under `docs/qa/e36-rule-form-editor/` in the repo (not in a wiki) so it versions with the code. Fixtures live under `fixtures/rule-ir/` and are loaded by both the frontend and backend test suites.

## Test plan
Self-referential: the plan is reviewed by the implementing engineers and the Architect; a reviewer must be able to execute any case without asking the author a question.

## Security notes
Charters explicitly include hostile-bundle import and cross-account scope attempts, which E36-X02 then automates. Fixtures must not contain real account ids or keys.

## Accessibility notes
The keyboard-only charter is mandatory, not optional — the form editor is the mandated accessible alternative to the node canvas (CMP-146).

## Performance notes
The plan names the budgets each perf case asserts: ≤300 ms validation, ≤500 ms p95 compile/round-trip, ≤4 ms/frame list scripting, ≤300 ms template instantiation, ≤2 s 100-rule import.

## Observability
Test cases assert that the audit events fire (`rule.created|saved|validated|roundtrip_verified|exported|imported`), since an unaudited rule change is itself a defect.

## Definition of Done
Plan and charters merged; fixtures committed and consumed by at least one automated test; traceability table complete; QA lead and Architect approval; linked from every E36-S* ticket.

## Dependencies
`blocked_by`: **E36-D05** (the handoff pack fixes the states and copy to test against), **E36-T01** (the fixture corpus lives with the package).

## Branch
`chore/e36-qa-plan`.

## References
`docs/plan/03-testing-strategy.md` · `docs/plan/02-definition-of-ready-done.md` · `docs/plan/14-screens-catalogue.md` §6 · `docs/plan/11-user-stories.md` §20.
""")

add("E36-Q02", "Task", "Automate the Playwright E2E suite for rule authoring, templates, list and import/export",
    ["type/test", AREA, "priority/p0", "qa"], "web", "Sprint 17", "P0 Critical", "Test", "R5 Scope", 3,
    "E36", ["E36-Q01", "E36-S02"], """
## Context
R3's E2E gate requires Playwright coverage of "rule creation in both editors" (`30-release-roadmap.md` §7.4). E36 owns the form half plus the surrounding screens; E37 extends the same suite for the graph. The byte-identity round-trip test is an R3 exit criterion (§7.3 item 5), so it lives here as a required check rather than as an optional suite.

## Scope / Deliverables
- Playwright specs (web + Electron shell) under `e2e/rules/`:
  1. **Author and save**: new rule → condition `unrealized_r_multiple >= 1` → action `move_to_breakeven` → scope → save → assert version 1, mode disabled, audit event, plain-language summary.
  2. **Grouped logic**: build A AND (B OR C), save, reload, assert the grouping is unchanged.
  3. **Invalid save**: metric with no data source → save refused, diagnostic anchored, focus moves to the offending row from the validation panel.
  4. **Opaque-region preservation**: load a graph-authored fixture, edit an unrelated threshold, save, assert the graph-only sub-tree is byte-identical (R3 exit criterion).
  5. **Round-trip mismatch**: divergent fixture → save and arm blocked, diff shown, both recovery choices present.
  6. **Templates**: instantiate three templates, assert the draft IR and the estimated-detector badge.
  7. **List**: filter, bulk disarm confirmation naming each rule, live WS state change applied in place, engine-down banner.
  8. **Import/export**: export → assert no account ids in the bundle → import as a second user → assert disarmed and remapped scope → import a hostile bundle → assert per-rule skip with reason.
  9. **Keyboard-only authoring**: the full authoring path driven purely by keyboard, asserting focus and announcements.
  10. **Concurrency**: two contexts editing the same rule → the second save is refused with the concurrency error.
- Deterministic backends: API and WS mocked from the E36-Q01 fixtures for the UI-level specs, plus a smaller integration subset run against the real API in the staging pipeline.
- CI wiring: the suite runs on every PR touching `apps/web/src/features/rules/**` or `packages/rule-editor-core/**`, and specs 4 and 5 are marked **required checks**.
- Flake policy: zero tolerance — any spec that flakes twice is quarantined with an owning ticket, never retried into green.

## Out of scope
Unit and component tests (owned by the stories). Graph-editor specs (E37). Load/perf (E36-Q04). Security-specific assertions beyond the two above (E36-X02).

## Acceptance criteria
```gherkin
Scenario: The suite is green and meaningful
  Given the ten specs
  When they run in CI against a fresh build
  Then all pass, and mutating an intentional defect (dropping an opaque region) makes spec 4 fail
Scenario: Round-trip preservation is a required check
  Then specs 4 and 5 are configured as required status checks and cannot be skipped by a label
Scenario: Keyboard-only path has no pointer events (a11y)
  Given spec 9
  Then the test harness asserts that no mouse event was dispatched during the run
Scenario: A flaky spec is quarantined, not retried (failure)
  Given a spec that fails intermittently
  Then it is quarantined with an owning ticket and the suite reports the quarantine rather than masking it with retries
```

## Technical notes / design
Page objects per screen so E37 reuses them. Fixture-driven mocking via route interception; WS mocked with a scripted `RuleUpdate` stream matching `23-ws-protocol.md` §15.6. Time is frozen where "last fired" is asserted.

## Test plan
The suite is itself validated by mutation: three deliberate defects (drop opaque region, anchor a diagnostic to the wrong row, allow a concurrent overwrite) must each make a specific spec fail.

## Security notes
Spec 8 asserts the export privacy promise and the hostile-bundle rejection; these assertions are referenced by E36-X02 rather than duplicated.

## Accessibility notes
Spec 9 is the automated keyboard gate; deeper auditing is E36-Q03. axe-core assertions run per screen inside the suite as a smoke level, not as a replacement for the audit.

## Performance notes
The suite must complete in ≤10 min in CI; long perf assertions belong to E36-Q04.

## Observability
Specs assert the audit events fire where the catalogue says they do.

## Definition of Done
Ten specs merged and green; required checks configured; mutation validation recorded; page objects documented for E37; QA lead approval.

## Dependencies
`blocked_by`: **E36-Q01** (plan and fixtures), **E36-S02** (the editor must exist). Specs 4/5 additionally need E36-S03, specs 6–8 need S04/S05/S06 and are merged as those land.

## Branch
`test/e36-rules-e2e`.

## References
`docs/plan/03-testing-strategy.md` · `docs/plan/30-release-roadmap.md` §7.3, §7.4 · `docs/plan/23-ws-protocol.md`.
""")

add("E36-Q03", "Task", "Accessibility audit of the rule form editor and its supporting screens",
    ["type/test", AREA, "priority/p0", "qa", "a11y"], "web", "Sprint 17", "P0 Critical", "QA", "R5 Scope", 3,
    "E36", ["E36-Q01", "E36-S02", "E36-D04"], """
## Context
`30-release-roadmap.md` §7.4 makes "both rule editors fully keyboard-operable" an R3 quality gate, and CMP-146 makes the form editor the *mandated* accessible equivalent of the node canvas. A failure here blocks E37 as well as E36. This audit measures the built software against the acceptance list produced in E36-D04.

## Scope / Deliverables
- WCAG 2.2 AA audit (`docs/plan/05-accessibility-standard.md`) of SCR-080, SCR-081, SCR-083, SCR-088, SCR-089 and every component state in Storybook, criterion by criterion, recorded pass/fail/N-A with evidence.
- Automated: axe-core over every screen state and every Storybook story, wired as a CI gate for the rules feature.
- Manual: two full screen-reader passes (NVDA + Firefox on Windows, VoiceOver + Safari on macOS) of the authoring flow, the validation panel's focus-to-anchor mechanism, the round-trip indicator state changes, the graph-only read-only card, the IR inspector's tree alternative and the import preview table.
- Keyboard audit: complete authoring with no pointer; every documented hotkey (`Ctrl+S`, `Ctrl+Enter`, `Alt+G`, `Alt+↑/↓`, `Ctrl+D`) verified for conflicts with AT pass-through and verified to have a visible control equivalent.
- Zoom/reflow at 200 %, 400 % where applicable; contrast measurement of all four round-trip indicator states, all armed-state tags and the estimated badge; target sizes ≥24×24.
- Announcement quality review: no announcement storm during validation; polite for counts, assertive only for blocking mismatch; row add/remove/reorder announced with position.
- A defect list with severity, each mapped to the failing success criterion, and retest after fixes.

## Out of scope
Design-stage review (E36-D04). The node canvas (E37 has its own audit). Functional QA (E36-Q05).

## Acceptance criteria
```gherkin
Scenario: No Level A or AA failures remain
  Given the full criterion checklist
  Then every applicable criterion passes, or is covered by a documented, Owner-accepted exception with a remediation ticket
Scenario: A rule can be authored end to end with a screen reader
  Given NVDA and VoiceOver passes of the authoring flow
  Then the tester can create, validate, correct and save a rule using only the screen reader and keyboard, and every state change is announced
Scenario: Diagnostics are reachable without sight or a pointer (edge)
  Given a rule with three errors
  Then the validation panel entries are focusable buttons that move focus to the offending row, and this is the demonstrated keyboard mechanism
Scenario: A colour-only signal is found (failure)
  Given any state distinguished only by colour
  Then it is filed as a blocker and the epic does not close until it is fixed
```

## Technical notes / design
axe-core runs per Storybook story via the test runner and per route in the E2E suite; violations fail the build for the rules feature paths. Manual findings are recorded with screenshots/recordings and the exact SC reference.

## Test plan
This ticket *is* the test. Retest cycle: audit → defects → fixes → targeted retest → sign-off comment.

## Security notes
N/A.

## Accessibility notes
The audit is measured against the D04 acceptance list one-to-one; anything in the build not in the list is still audited, and the list is updated so E37 inherits the corrected version.

## Performance notes
Verify that assistive-technology usage does not degrade responsiveness (announcement throttling, live-region churn under rapid validation).

## Observability
N/A.

## Definition of Done
Criterion checklist complete with evidence; axe CI gate wired and green; both screen-reader passes recorded; all Level A/AA defects fixed and retested; accessibility specialist and QA lead sign-off; results linked from the epic and referenced by E37's a11y gate.

## Dependencies
`blocked_by`: **E36-Q01**, **E36-S02**, **E36-D04**.

## Branch
`test/e36-a11y-audit`.

## References
`docs/plan/05-accessibility-standard.md` · `docs/plan/15-component-catalogue.md` CMP-146, CMP-234 · `docs/plan/30-release-roadmap.md` §7.4.
""")

add("E36-Q04", "Task", "Build the performance benchmarks for validation, compile round-trip, list and import",
    ["type/test", AREA, "priority/p1", "qa", "perf"], "web", "Sprint 17", "P1 High", "Test", "R2 Render performance", 2,
    "E36", ["E36-Q01", "E36-S05"], """
## Context
The rule editor carries four explicit budgets (`14-screens-catalogue.md` SCR-080/081/083/089, `06-performance-and-load-standard.md`). They matter because the compile/round-trip check runs on save and on every editor-mode switch — if it is slow, users will switch editors less, which undermines the dual-editor promise, and if the list is slow the entry point to the whole rule engine feels broken.

## Scope / Deliverables
- Benchmarks, run in CI on the reference machine and recorded over time:
  1. **Validation round-trip** ≤300 ms p95 — measured from keystroke-debounce fire to diagnostics rendered, with a recorded `POST /rules/validate` latency profile so client and server contributions are separable.
  2. **Compile + round-trip diff** ≤500 ms p95 on the 100-node rule fixture, measured on save and on mode switch.
  3. **Rules list** — 500-row fixture, scripting ≤4 ms per frame during scroll, plus the cost of applying a burst of `rules` WS updates at the 250 ms topic cadence.
  4. **Template instantiation** ≤300 ms from confirm to the editor being interactive.
  5. **Import** — 100-rule bundle validated in ≤2 s with results streamed, main thread never blocked >50 ms in a single task.
  6. **`rule-editor-core`** — `irToForm`/`formToIr` ≤10 ms on the 100-node fixture.
- A k6 script for the backend side of the editor's read path (`GET /rules`, `GET /rules/vocabulary`, `POST /rules/validate`) at the concurrency the product expects, to confirm the client budgets are not being met only because the server is idle.
- A results dashboard entry and a CI regression guard: a >20 % regression against the recorded baseline fails the build.

## Out of scope
Chart-engine FPS work. Rule *runtime* evaluation performance (E35). Node-canvas FPS with 100 nodes (E37).

## Acceptance criteria
```gherkin
Scenario: Every budget has a measurement
  Given the six budgets
  Then each has an automated benchmark producing a number, and the number is recorded against the budget in the catalogue
Scenario: A regression fails the build
  Given a change that makes validation 25% slower
  Then the CI guard fails with the before/after numbers
Scenario: A budget is missed (failure)
  Given a measured p95 above its budget
  Then the ticket is not closed: either the code is optimised or an explicit, Owner-accepted budget change is recorded in 06-performance-and-load-standard.md
Scenario: Long-task compliance (edge)
  Given the 100-rule import
  Then no single main-thread task exceeds 50 ms, verified from the performance trace
```

## Technical notes / design
Browser measurements via Playwright + the Performance API (`performance.measure`, long-task observer); component-level measurements via a benchmark harness in the package. Fixtures come from E36-Q01. Runs pinned to the reference machine profile defined in `06-performance-and-load-standard.md` so numbers are comparable across sprints.

## Test plan
Benchmarks are validated by injecting a known 200 ms delay and confirming each harness reports it.

## Security notes
k6 scripts run against staging with test credentials only; no production or live-trading environment is load-tested.

## Accessibility notes
Measure with a screen reader active in at least one run — live-region churn is a real cost on the validation path.

## Performance notes
This ticket is the performance artefact; the achieved numbers replace the targets in the catalogue via E36-T02.

## Observability
Emit the client metrics the app already defines (`rule_editor_validate_latency_ms`, `rule_editor_compile_latency_ms`) so production numbers can be compared with the lab numbers.

## Definition of Done
Six benchmarks automated and baselined; k6 script committed; regression guard wired; numbers recorded and handed to E36-T02 for the docs; perf owner approval.

## Dependencies
`blocked_by`: **E36-Q01** (fixtures), **E36-S05** (the list is one of the subjects). Benchmarks 1, 2 and 6 can start once E36-S03 lands.

## Branch
`test/e36-perf-benchmarks`.

## References
`docs/plan/06-performance-and-load-standard.md` · `docs/plan/14-screens-catalogue.md` SCR-080, SCR-081, SCR-083, SCR-089 · `docs/plan/03-testing-strategy.md`.
""")

add("E36-Q05", "Task", "Run the exploratory charters, assemble the regression pack and give QA sign-off",
    ["type/test", AREA, "priority/p0", "qa"], "web", "Sprint 18", "P0 Critical", "QA", "R5 Scope", 3,
    "E36", ["E36-Q02", "E36-Q03", "E36-Q04", "E36-S06"], """
## Context
`02-definition-of-ready-done.md` requires a QA sign-off per feature and an epic-level regression/exploratory pass, not just child-ticket testing. This is that pass for E36, and its output — the regression pack — is what E37 and E40 run against when they change shared components.

## Scope / Deliverables
- Execute the five exploratory charters from E36-Q01 (data-loss hunting, form/graph boundary, keyboard-only, hostile bundles, list under live state change), each time-boxed at 90 min with a written debrief and filed defects.
- Execute the full black-box test plan against a staging build, recording results per case.
- Verify each story's acceptance scenarios are genuinely met end to end, including the ones automation covers (spot-check, do not assume).
- Assemble the **E36 regression pack**: the subset of cases that must be re-run whenever CMP-140..145, CMP-157, CMP-233..235 or `packages/rule-editor-core` change — this is the pack E37 (node editor) and E40 (alerts, which reuses the condition editor) inherit.
- Cross-epic verification with E35: run the shared IR corpus through form → save → reload and confirm the hashes the server reports are stable, evidencing roadmap exit criterion §7.3 item 5 from the form side.
- Defect triage to zero P0/P1 against E36 scope; severity rubric from E36-Q01.
- Written QA sign-off comment on the epic with the evidence links.

## Out of scope
Fixing defects (they go to the owning story or a new Bug). Security sign-off (E36-X03). Design sign-off (E36-D06).

## Acceptance criteria
```gherkin
Scenario: All charters executed and debriefed
  Given the five charters
  Then each has a debrief note listing what was covered, what was not, and the defects found
Scenario: Zero P0/P1 at sign-off
  Given the defect list for E36 scope
  Then no P0 or P1 remains open, or each is explicitly deferred with Owner acceptance recorded
Scenario: The regression pack is usable by another epic (edge)
  Given an engineer on E37 changing CMP-234
  Then they can run the E36 regression pack without asking QA how, and it reports pass/fail per case
Scenario: A charter finds a data-loss defect (failure)
  Given any scenario in which an edit loses or rewrites a graph-authored sub-tree
  Then it is filed as a blocker, E36 cannot close, and a regression test is added to the E2E suite before the fix is accepted
```

## Technical notes / design
Session-based test management: charter, time box, session notes, bug list, coverage estimate. Staging build deployed from `main`.

## Test plan
This ticket is the execution; its own quality bar is that every filed defect is reproducible from the written steps by someone else.

## Security notes
The hostile-bundle charter overlaps E36-X02; findings are shared so the security suite gains any case QA discovers by hand.

## Accessibility notes
The keyboard-only charter is run with the mouse physically unplugged; findings feed E36-Q03's retest cycle.

## Performance notes
Charters note any perceived slowness; quantitative confirmation is E36-Q04's.

## Observability
Verify audit events exist for every state-changing action performed during the charters — a missing audit row is a defect.

## Definition of Done
All charters executed and debriefed; full plan executed with results recorded; regression pack published and linked from E37 and E40; zero open P0/P1; QA sign-off comment on the epic with evidence.

## Dependencies
`blocked_by`: **E36-Q02**, **E36-Q03**, **E36-Q04**, **E36-S06** (the last feature story).

## Branch
N/A (execution ticket; defects get `fix/` branches).

## References
`docs/plan/03-testing-strategy.md` · `docs/plan/02-definition-of-ready-done.md` · `docs/plan/30-release-roadmap.md` §7.3.
""")

# ------------------------------------------------------------------ SECURITY
add("E36-X01", "Task", "Produce the STRIDE threat model for the rule authoring surface",
    ["type/security", AREA, "priority/p0", "security"], "web", "Sprint 15", "P0 Critical", "Security", "R4 Script sandbox", 3,
    "E36", ["E35", "E36-D02"], """
## Context
`docs/plan/04-security-program.md` mandates a STRIDE threat model per epic, and `30-release-roadmap.md` §7.4 lists the rule engine (E35) among the R3 epics whose Critical/High findings must all be closed. E36 is the *authoring* half of that system: a UI that lets a human define automated order placement, stop modification and position flattening across accounts. Its threats are different from the runtime's — they are about what a rule can be made to say, and about who can make it say that.

## Scope / Deliverables
- Data-flow diagram of the authoring path: browser → `POST /rules/validate` → `POST /rules/{ruleId}/compile` → `POST|PUT /rules` → `rules`/`rule_versions` (Postgres) → runtime (E35), including the import/export side channel and the WS `rules` topic.
- STRIDE enumeration per element and per trust boundary, at minimum:
  - **S**poofing: session reuse across tabs; a rule attributed to the wrong author.
  - **T**ampering: a crafted IR submitted directly to the API bypassing the UI; a tampered import bundle; a mutated `presentation` block used as a smuggling channel.
  - **R**epudiation: rule edits or import/export without audit; an armed rule whose authorship cannot be established.
  - **I**nformation disclosure: exported bundles carrying account ids or scope bindings; the IR inspector exposing another user's rule; the vocabulary revealing accounts or symbols the user may not see; error messages leaking internal paths.
  - **D**enial of service: a pathological IR (deep nesting, enormous literal set) blocking the browser or the validate endpoint; validation request storms from an un-debounced editor.
  - **E**levation of privilege: authoring a rule scoped to an account the user cannot trade; a manager creating an order-placing rule without live-arming permission (US-RULE-003 requires such actions to be simulate-only for them); using import to introduce a scope the UI would not offer.
- Risk rating (likelihood × impact) with the existing register (`docs/plan/32-risk-register.md`), mapping to R4 Script sandbox and R13 Sharing abuse.
- Mitigations assigned to concrete tickets: server-side scope intersection and 403 (E36-S01/S02), export stripping and import remap (E36-S06), parser size/depth guards (E36-T01), audit events (all stories), debounce and request cancellation (E36-S02).
- Abuse cases written up for E36-X02 to automate.
- An explicit statement of what E36 does **not** defend against because E35/E39 own it (evaluation sandboxing, execution-time budget, kill-switch, risk caps) so there is no gap between the models.

## Out of scope
The runtime threat model (E35's). Key vault (E27). Pen-test (E43).

## Acceptance criteria
```gherkin
Scenario: Every element has a STRIDE row
  Given the data-flow diagram
  Then each element and trust boundary has all six categories considered, with an explicit "not applicable, because…" where a category does not apply
Scenario: Every Critical/High has an owner and a ticket
  Given the rated findings
  Then each Critical or High names a mitigation, a ticket key and a target sprint inside R3
Scenario: Privilege escalation via import is modelled (edge)
  Given the import path
  Then the model states exactly where account references are remapped or rejected, and names the test that proves it
Scenario: A gap between E35 and E36 is found (failure)
  Given a threat neither model owns
  Then it is assigned in writing to one of the two epics before this ticket closes
```

## Technical notes / design
Model documented under `docs/security/threat-models/e36-rule-form-editor.md` using the program's template; diagram in mermaid so it versions in the repo.

## Test plan
The model's claims become the E36-X02 test suite; a claim with no test is not an accepted mitigation.

## Security notes
This ticket *is* the security artefact. Data classification: rule content is internal-confidential; account bindings within a rule are sensitive because they connect a user to tradable capital.

## Accessibility notes
N/A.

## Performance notes
The DoS analysis sets the concrete parser limits (max document bytes, max nesting depth, max conditions/actions) that E36-T01 enforces — the numbers are decided here, not guessed in code.

## Observability
Specifies the audit events and the alertable security signals: repeated 403s on rule scope, a spike in `rule_ir_invalid`, import of bundles with foreign account references.

## Definition of Done
Model merged and reviewed by the Security engineer and the Architect; findings triaged with tickets; parser limits published; abuse cases handed to E36-X02; linked from the epic.

## Dependencies
`blocked_by`: **E35** (the IR and endpoint surface being modelled), **E36-D02** (the designed flows, so the model covers what will actually ship).

## Branch
`chore/e36-threat-model`.

## References
`docs/plan/04-security-program.md` · `docs/plan/32-risk-register.md` · `docs/plan/22-api-openapi.yaml` (rules tag) · `docs/plan/11-user-stories.md` US-RULE-003, US-RULE-007.
""")

add("E36-X02", "Task", "Implement the abuse-case suite, scope assertions and SAST rules for rule authoring",
    ["type/security", AREA, "priority/p0", "security"], "web", "Sprint 17", "P0 Critical", "Security", "R4 Script sandbox", 3,
    "E36", ["E36-X01", "E36-S02"], """
## Context
E36-X01's model is only worth what its tests prove. This ticket turns each Critical/High finding into an automated assertion that runs in CI, so a regression in the authoring surface fails a build rather than being found in a pen-test.

## Scope / Deliverables
- **Scope/permission assertions** (API-level, run against a test backend):
  - A manager without trading permission on account X cannot create or update a rule scoped to X — 403, no row written, audit row present (US-RULE-007).
  - The account list returned to that manager never contains X (not merely disabled).
  - A manager without live-arming permission can only save order-placing actions in simulate context; the restriction is explained rather than silently applied (US-RULE-003).
  - A `viewer` receives 403 on every rules write endpoint and no rule data on reads they are not granted.
- **Crafted-payload tests** posted directly to the API, bypassing the UI: an IR with a foreign account reference; an IR with an unknown action; an IR whose `presentation` block carries an enormous payload; an IR nested beyond the depth limit; a rule id belonging to another user.
- **Import abuse tests**: a bundle carrying account bindings, a bundle declaring an armed state, a bundle with a newer schema version, a bundle with a 50 MB payload, a bundle with 10 000 rules — each must be rejected or remapped per the model, never partially applied.
- **Export privacy test**: scan every exported bundle for any known account id, key id or armed-state field; fail on any hit.
- **DoS guards**: assert the parser limits from E36-X01 are enforced client-side before parse and server-side on validate; assert the editor debounces and cancels in-flight validation so a fast typist cannot generate a request storm.
- **SAST/DAST**: Semgrep rules for the rules feature paths — no `dangerouslySetInnerHTML`, no `eval`/`Function` construction, no direct `innerHTML` with rule content, no client-side-only authorisation check gating a write; a ZAP profile covering the rules endpoints with the crafted payloads above.
- Wire everything into CI as required checks on the rules feature paths.

## Out of scope
Runtime sandboxing and execution budget (E35). Key management (E27). Full pen-test (E43).

## Acceptance criteria
```gherkin
Scenario: Every High/Critical finding has a passing test
  Given the E36-X01 findings
  Then each Critical or High maps to at least one automated assertion in this suite, and the mapping is documented
Scenario: A crafted request cannot escalate scope
  Given a direct API call creating a rule scoped to an account the caller cannot trade
  Then the response is 403, no rules or rule_versions row is written, and an audit entry records the attempt
Scenario: Export cannot leak bindings (failure)
  Given a deliberately reintroduced bug that leaves account ids in the bundle
  Then the export privacy scan fails the build
Scenario: Pathological documents are refused fast (edge)
  Given a 50 MB bundle and a 10 000-deep nested IR
  Then both are refused before parsing completes, with a clear error, and neither blocks the browser main thread for more than 50 ms nor the API worker beyond its timeout
Scenario: SAST catches an unsafe rendering pattern
  Given a change introducing dangerouslySetInnerHTML into the rules feature
  Then the Semgrep rule fails the PR
```

## Technical notes / design
API-level tests live with the backend suite (they assert server behaviour, which is where authorisation lives); UI-level guards are asserted in the frontend suite. The export scan is a small script fed the tenant's known account ids from the test fixture.

## Test plan
Each assertion is validated by mutation — reintroduce the vulnerability, confirm the test fails — and that validation is recorded on the ticket.

## Security notes
This suite is the epic's standing security regression. Findings that cannot be automated are recorded as manual checks in E36-X03's review checklist rather than dropped.

## Accessibility notes
N/A.

## Performance notes
The suite must run in ≤5 min so it can be a required check; the 10 000-rule bundle case runs in a nightly job rather than per PR.

## Observability
Assert that every rejected attempt writes an audit row and increments the security counters named in E36-X01 (403-on-scope, `rule_ir_invalid` spike, foreign-account import).

## Definition of Done
Suite merged and green; mutation validation recorded per assertion; Semgrep rules and ZAP profile committed and wired; required checks configured; Security engineer review.

## Dependencies
`blocked_by`: **E36-X01** (the findings), **E36-S02** (the surface). Import/export assertions land with E36-S06.

## Branch
`test/e36-security-suite`.

## References
`docs/plan/04-security-program.md` · `docs/plan/22-api-openapi.yaml` (x-rbac on the rules tag) · `docs/plan/11-user-stories.md` US-RULE-003, US-RULE-007 · `docs/plan/03-testing-strategy.md`.
""")

add("E36-X03", "Task", "Security review and sign-off of the shipped rule authoring surface",
    ["type/security", AREA, "priority/p0", "security"], "web", "Sprint 18", "P0 Critical", "Security", "R13 Sharing abuse", 2,
    "E36", ["E36-X02", "E36-S06", "E36-Q05"], """
## Context
R3's security gate requires that all Critical/High STRIDE findings for the rule-engine epics are closed and that a targeted abuse-case review of privilege escalation happens before the train closes (`30-release-roadmap.md` §7.4). This is E36's closing review and the sign-off the epic cannot be Done without.

## Scope / Deliverables
- White-box review of the shipped rules feature: `apps/web/src/features/rules/**`, `packages/rule-editor-core/**` and the client bindings, looking specifically for authorisation decisions made client-side, unsanitised rendering of rule content, missing audit calls, and any place the client asserts something the server does not re-check.
- Verification pass over every E36-X01 finding: closed / mitigated / accepted-with-Owner-sign-off, with evidence (test name, code reference or Owner comment).
- Manual abuse-case session complementing the automated suite: attempt privilege escalation through the editor, the import path and the API directly, including cross-tab session tricks and replaying a stale rule version.
- Verify the two catalogue promises hold in the shipped build: exported bundles contain no account ids, keys or armed state; imported rules always land disarmed.
- Verify audit completeness: every state-changing action in the epic (`rule.created|updated|saved|validated|roundtrip_verified|roundtrip_mismatch_resolved|exported|imported|deleted|disarmed`) produces an audit row with actor, rule id and version, and that the rows survive the audit hash-chain verification used by E42.
- Dependency and supply-chain check for anything new the epic introduced (`npm audit`, licence review of any new library used by the editor).
- Written sign-off comment on the epic, or an explicit list of blockers preventing it.

## Out of scope
Pen-test (E43). Runtime/evaluation security (E35). Key vault (E27).

## Acceptance criteria
```gherkin
Scenario: No open Critical or High findings
  Given the E36-X01 register
  Then every Critical and High is closed or explicitly accepted by the Owner with a recorded rationale and a follow-up ticket
Scenario: Authorisation is never client-side only
  Given the code review of every write path in the rules feature
  Then each has a corresponding server-side check, evidenced by an assertion in the E36-X02 suite
Scenario: Audit completeness (edge)
  Given each state-changing action performed manually during the review
  Then a matching audit row exists with actor, rule id and version, and hash-chain verification passes
Scenario: A blocker is found (failure)
  Given any exploitable privilege escalation or data leak
  Then the epic cannot be signed off, the finding is filed at P0, and the fix carries its own regression test before re-review
```

## Technical notes / design
Review conducted against the `main` build that is a candidate for the R3 PRR; findings recorded in the threat-model document so it stays the living record.

## Test plan
Manual review plus re-running E36-X02 and the E2E security specs against the candidate build; any new finding becomes a new automated assertion before sign-off.

## Security notes
This ticket is the gate. Data classification confirmed: rule content internal-confidential; audit rows are append-only and retained indefinitely (US-RULE-010 NFR).

## Accessibility notes
N/A.

## Performance notes
Confirm the DoS guards (document size, nesting depth, debounce/cancel) are present in the shipped build, not only in the tests.

## Observability
Confirm the security signals from E36-X01 are wired to alerting: repeated scope 403s, `rule_ir_invalid` spikes, foreign-account import attempts.

## Definition of Done
All findings dispositioned; manual abuse session recorded; audit completeness verified; supply-chain check clean; Security engineer sign-off comment on the epic; the threat-model document updated to the shipped state.

## Dependencies
`blocked_by`: **E36-X02** (the automated suite must exist to be verified against), **E36-S06** (the last security-relevant surface), **E36-Q05** (QA pass complete so the build under review is the candidate).

## Branch
N/A (review ticket).

## References
`docs/plan/04-security-program.md` · `docs/plan/30-release-roadmap.md` §7.4 · `docs/plan/07-release-and-prr.md` · `docs/plan/14-screens-catalogue.md` SCR-089.
""")

json.dump(T, open(os.path.join(os.path.dirname(__file__), "backlog", "_e36_c.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(len(T), sum(t["estimate"] for t in T))
