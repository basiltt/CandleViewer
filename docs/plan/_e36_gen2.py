# -*- coding: utf-8 -*-
import json, os

PHASE = "P3 Drawing & Alerts"; MILE = "R3 Trading on demo"; AREA = "area/rule-engine"
T = []
def add(key, kind, title, labels, component, sprint, priority, perspective, risk, estimate, parent, blocked_by, body):
    T.append({"key": key, "kind": kind, "title": title, "labels": labels, "component": component,
        "phase": PHASE, "sprint": sprint, "priority": priority, "perspective": perspective,
        "risk": risk, "estimate": estimate, "parent": parent, "blocked_by": blocked_by,
        "milestone": MILE, "body": body.strip() + "\n"})

add("E36-T01", "Task", "Build packages/rule-editor-core: form model, IR adapter, vocabulary cache, diagnostics anchoring",
    ["type/tech", AREA, "priority/p0"], "web", "Sprint 16", "P0 Critical", "Development", "R5 Scope", 3,
    "E36", ["E35", "E36-D05"], """
## Context
Both the form editor (E36) and, later, the graph editor (E37) need a framework-free layer between the server's canonical `RuleIr` and whatever the UI edits. Putting that layer in a package keeps the round-trip contract (OD#11, US-RULE-001) testable without React and stops the editor from ever computing semantics the server owns.

The server is the only authority: `POST /api/v1/rules/validate` returns diagnostics, `POST /api/v1/rules/{ruleId}/compile` returns canonical IR plus `ir_hash`, `GET /api/v1/rules/vocabulary` enumerates every legal signal, operator, action and guard (`22-api-openapi.yaml`, rules tag; `24-internal-schemas.md` §11.6). This package must never re-implement any of that — it maps, caches and anchors.

## Scope / Deliverables
- New package `packages/rule-editor-core` (TypeScript, no React, no DOM), exporting:
  - `FormModel` types: `{ scope, trigger, conditionGroups, actions, options, presentation, opaqueRegions }` where `opaqueRegions` holds verbatim IR sub-trees the form cannot represent.
  - `irToForm(ir: RuleIr, vocab: RuleVocabulary): FormModel` — every sub-tree that has no form representation becomes an `OpaqueRegion { irPointer, rawNode, plainLanguageSummary, reason }` carrying the original JSON **byte-for-byte**.
  - `formToIr(model: FormModel): RuleIr` — re-inserts opaque regions unchanged at their JSON pointer and leaves the `presentation` block untouched (US-RULE-001: presentation is excluded from the hash and must survive a form save).
  - `VocabularyCache`: ETag-conditional fetch of `GET /rules/vocabulary`, typed lookup by metric/action id, category filtering for CMP-157, `isEstimated(metricId)`, unit and valid-range access, and an `unknownIdentifier` path so a loaded IR referencing an identifier absent from the vocabulary yields a disabled row naming it rather than a dropped condition.
  - `anchorDiagnostics(diagnostics, model)`: maps `RuleValidationResult` entries (`{path, code, message}`) onto form rows/groups/actions, producing CMP-234's `{id,severity,message,anchor:{kind:"row",id},fixHint}` shape; unmappable diagnostics surface as rule-level entries, never swallowed.
  - `summarise(model, vocab): string` — the plain-language rule summary used as the accessible description (US-RULE-004 NFR) and on SCR-080 rows.
  - `validateLocally(model)`: *presentation-level* checks only (missing value in a row, empty action list) used for instant feedback; explicitly documented as advisory, with the server's verdict always winning.
- API client bindings for the six endpoints used, generated from `22-api-openapi.yaml`, with the problem-catalogue codes typed (`rule_ir_invalid`, optimistic-concurrency conflict).
- A shared test corpus `fixtures/rule-ir/*.json` of ≥30 IR documents (simple, grouped, nested, opaque-region, unknown-identifier, migrated-version, 100-node) shared with E35's round-trip corpus.

## Out of scope
React components (E36-S01/S02). Canonicalisation, hashing, migrations, evaluation (E35). Node-graph model (E37).

## Acceptance criteria
```gherkin
Scenario: Round trip through the form model is lossless
  Given any IR document in fixtures/rule-ir
  When it is converted with irToForm and back with formToIr
  Then the resulting document is deep-equal to the input, including the presentation block and every opaque region
Scenario: An unrepresentable construct is preserved, not dropped
  Given an IR containing a fan-out where one metric node feeds two actions
  When it is loaded and an unrelated threshold is changed and serialised back
  Then the fan-out sub-tree is byte-identical to the original and is exposed as an OpaqueRegion with a plain-language summary
Scenario: An unknown identifier does not corrupt the rule (error)
  Given an IR referencing metric "quantum_flux" which the vocabulary does not contain
  Then irToForm yields a row flagged unknownIdentifier naming "quantum_flux", formToIr re-emits it unchanged, and no exception is thrown
Scenario: Diagnostics anchor to the right row (edge)
  Given a diagnostic at path "then[0].params.price"
  Then anchorDiagnostics returns an anchor pointing at the first action row, and a diagnostic at an unmappable path returns a rule-level anchor rather than being discarded
Scenario: Vocabulary cache honours ETag
  Given a cached vocabulary and a 304 response
  Then no re-parse occurs and the cached typed lookup is reused
```

## Technical notes / design
- Opaque regions are addressed by RFC 6901 JSON pointers; `formToIr` rebuilds the document by writing form-derived nodes into a structural clone of the original IR, so anything the form never touched is literally the same value — this is the cheapest way to guarantee the byte-identity requirement rather than trying to re-serialise faithfully.
- Number handling: never reformat numerics client-side (1.50 vs 1.5 matters only to canonicalisation, which is the server's job); carry literals as strings where the IR does.
- `summarise` grammar comes from E36-D01's research output; estimated metrics are rendered with the "(estimated)" suffix inside the summary text itself so the badge is never colour/icon-only.
- No global state; the package takes an injected fetch implementation so tests run without network.

## Test plan
Unit (target ≥90 % lines on this package, above the 80 % FE floor because it is the round-trip guarantee): every fixture through the lossless round-trip property; a fast-check property test generating form models and asserting `irToForm(formToIr(m))` stability; diagnostics anchoring table tests; vocabulary cache ETag/404/malformed-response tests; unknown-identifier tests. Contract tests validate the client bindings against `22-api-openapi.yaml` with a schema-driven mock. Fixtures shared with E35 so both sides fail together if the IR changes.

## Security notes
The package parses server-supplied and user-supplied JSON (imported bundles): enforce a maximum document size and nesting depth before parsing to avoid a pathological-document DoS in the browser; never `eval` or dynamically construct functions from IR content; treat every string as untrusted and let React escape it (no `dangerouslySetInnerHTML` anywhere downstream). Data classification: rule content is internal-confidential (it encodes trading behaviour).

## Accessibility notes
`summarise` output is consumed as an accessible description — it must be a complete sentence, contain no unexpanded identifiers, and state estimated-detector dependence in words.

## Performance notes
`irToForm`/`formToIr` on the 100-node fixture must complete in ≤10 ms on the reference machine so they can run on save and on mode switch inside the ≤500 ms p95 compile budget (`06-performance-and-load-standard.md`).

## Observability
Expose counters the app reports: `rule_editor_validate_latency_ms`, `rule_editor_compile_latency_ms`, `rule_editor_unknown_identifier_total`, `rule_editor_opaque_region_total`.

## Definition of Done
Package published in the monorepo with README; ≥90 % unit coverage; contract tests green; fixtures shared and referenced by E35; two approvals incl. a code owner; no public API left undocumented.

## Dependencies
`blocked_by`: **E35** (IR schema, vocabulary and validate/compile endpoints must be merged), **E36-D05** (the summary grammar and copy come from the handoff pack).

## Branch
`feat/rule-form-editor-core`. PR ≤400 LOC; split the client bindings into a second PR if needed.

## References
`docs/plan/22-api-openapi.yaml` (rules tag) · `docs/plan/24-internal-schemas.md` §11 · `docs/plan/11-user-stories.md` US-RULE-001, US-RULE-002 · `docs/plan/15-component-catalogue.md` CMP-234 · `docs/plan/03-testing-strategy.md`.
""")

add("E36-S01", "Story", "Build the condition, action, trigger and scope components of the form editor",
    ["type/feature", AREA, "priority/p0", "a11y"], "web", "Sprint 16", "P0 Critical", "Development", "R5 Scope", 5,
    "E36", ["E36-T01"], """
## Context
US-RULE-002 (metric vocabulary), US-RULE-003 (action vocabulary) and the row-level half of US-RULE-004 (form / condition-list editor) are delivered as design-system components so that the alert builder (E40, which reuses the condition editor minus execution actions — SCR-090 series) and the node inspector (E37) get them for free. This story builds the components; E36-S02 assembles them into the page.

## Scope / Deliverables
Components per `docs/plan/15-component-catalogue.md` §5, built to the D05 handoff pack:
- **CMP-140 RuleConditionRow** — `metric`, `operator` (`>` `>=` `<` `<=` `==` `!=` `crosses_above` `crosses_below`), `value: number | {metricRef}`, `joinToNext?: "AND"|"OR"`, `onChange`, `onRemove`, `invalid?`. Operator list is filtered by the metric's type from the vocabulary (`crosses_above` is not offered for boolean metrics). Value input switches between literal and metric-reference modes.
- **CMP-141 RuleConditionGroup** — `rows`, `mode: "and"|"or"|"advanced"`, `onAddRow`, `onChangeMode`; `fieldset`/`legend` grouping on CMP-065, indentation via `space.rulegroup.indent`, `aria-level` on the tree-like structure in advanced mode.
- **CMP-142 RuleActionRow** — `actionType`, `params`; the parameter form is rendered dynamically from the action's parameter schema in the vocabulary (CMP-040 FormField per parameter), covering at minimum {VOCAB_ACTIONS_SHORT}.
- **CMP-143 RuleTriggerPicker** — `on_price_update`, `on_bar_close`, `on_order_fill`, `on_timer`, `on_indicator` plus timeframe.
- **CMP-144 RuleScopeSelector** — symbol, accounts (reusing CMP-105 AccountMultiSelect), `appliesTo: open_positions | pending_orders | account`; **accounts the user may not trade are not listed at all** (US-RULE-007).
- **CMP-157 MetricPickerCombobox** — searchable over the whole metric vocabulary with category filter and descriptions; `(estimated)` tagged in the option list itself; a metric whose data dependency is missing renders disabled with the missing dependency named and a "start recording" action (US-RULE-002).
- **CMP-158 SafetyInvariantNotice** — static, non-dismissible `role="note"`.
- Storybook stories exactly as the catalogue lists them (CMP-140: Default, MetricRefValue, JoinAnd, JoinOr, Invalid; CMP-141: And, Or, AdvancedNested; CMP-142: PlaceOrder, ModifyStopLoss, MoveToBreakeven, ScaleOut, FlattenAll, HaltNewOrders; CMP-143: OnBarClose, OnFill, OnTimer, OnIndicator; CMP-144: SingleAccount, MultiAccount, AccountScope; CMP-157: Default, FilteredByCategory, EstimatedMetricTagged).

## Out of scope
The page composition, save/validate wiring and round-trip indicator (E36-S02/S03). Node components (E37). Anything that evaluates a rule.

## Acceptance criteria
```gherkin
Scenario: Operators are filtered by metric type
  Given the metric position_side, which is an enum
  When the operator list is opened
  Then crosses_above and crosses_below are not offered, and choosing == offers long/short rather than a numeric field
Scenario: An estimated metric is unmistakable
  Given the metric in_stop_hunt_zone
  Then the option in the picker, the selected row and the row's accessible name all contain "(estimated)"
Scenario: A metric with no data source is blocked, with a way out (error)
  Given a metric requiring recorded data the symbol lacks
  Then it is disabled in the picker, the missing dependency is named in text, and a one-click action to start recording that symbol is offered
Scenario: Accounts outside permission are invisible (security edge)
  Given a manager without trading permission on account "sub_002"
  When the scope selector's account list is opened
  Then sub_002 is absent entirely — not merely disabled
Scenario: Keyboard-only row authoring
  Given focus on a condition row
  When the user tabs through metric, operator, value and the remove control and presses Alt+Up
  Then the row moves up, the new position is announced ("Condition 1 of 3"), and no pointer was required
Scenario: Type mismatch is shown inline (failure)
  Given a numeric value typed against position_side
  Then the row shows "position_side compares to long/short, not a number." and the row is marked invalid
```

## Technical notes / design
Components are controlled and stateless; all vocabulary access goes through `rule-editor-core`'s `VocabularyCache`. Dynamic action parameter forms are schema-driven — do not hand-write a form per action type; add a renderer per parameter primitive (decimal, integer, enum, percentage, duration, price, symbol, account, boolean) so a new action in the vocabulary works without a frontend change. Invalid state is driven from the anchored diagnostics, never from local guessing beyond the advisory checks.

## Test plan
Unit per component (≥80 % lines): operator/metric compatibility matrix; enum vs numeric value rendering; metric-ref mode; join toggle; per-action-type parameter validation; permission filtering of the account list; estimated tagging. Visual regression per Storybook story. axe-core per story. Keyboard interaction tests: row reorder, remove, combobox navigation, group-mode switch. Contract test: every action type present in a recorded `GET /rules/vocabulary` fixture renders a parameter form without falling back to "unsupported".

## Security notes
The account list must be filtered from server-provided grants, never from a client-side role check that a crafted state could bypass; the server additionally rejects an out-of-permission scope with 403 (US-RULE-007) and the UI must surface that verbatim. No rule content is ever rendered as HTML.

## Accessibility notes
Per E36-D04's acceptance list: every row is a labelled group "Condition N of M"; the metric combobox follows the CMP-048 combobox pattern with descriptions announced; reorder announces the new position; `(estimated)` is part of the accessible name; remove is a labelled icon button; no drag requirement anywhere; CMP-158 is present and non-dismissible.

## Performance notes
The metric combobox filters 24+ metrics with no perceptible delay; rendering 12 condition rows plus 6 action rows stays within one frame. No component may trigger a vocabulary refetch on render.

## Observability
No audit events at component level; the page (S02) owns them. Report `rule_editor_unknown_identifier_total` when a row renders an unknown identifier.

## Definition of Done
All components in the catalogue's Storybook groups (`RuleEngine/*`); ≥80 % coverage; axe green; visual baselines committed; design QA input given to E36-D06; `15-component-catalogue.md` updated if any prop diverged; two approvals incl. code owner.

## Dependencies
`blocked_by`: **E36-T01** (form model, vocabulary cache, diagnostics anchoring). Design input from E36-D05 (already Done by Sprint 16 per design-ahead).

## Branch
`feat/rule-form-editor-rows`. Split into two PRs (condition side / action+scope side) to stay ≤400 LOC.

## References
`docs/plan/11-user-stories.md` US-RULE-002, US-RULE-003, US-RULE-004, US-RULE-007 · `docs/plan/14-screens-catalogue.md` SCR-081 · `docs/plan/15-component-catalogue.md` CMP-140..144, CMP-157, CMP-158 · `docs/plan/05-accessibility-standard.md`.
""".replace("{VOCAB_ACTIONS_SHORT}", "place_order, modify_stop_loss, modify_take_profit, cancel_order, move_to_breakeven, scale_out, scale_in, flatten_all_positions, halt_new_orders, resume_new_orders, send_notification, log_journal_tag, reduce_leverage, widen_stop, arm_chase_limit, start_iceberg_slice"))

add("E36-S02", "Story", "Ship SCR-081 rule editor page with validation, save and scoping",
    ["type/feature", AREA, "priority/p0", "a11y"], "web", "Sprint 16", "P0 Critical", "Development", "R4 Script sandbox", 5,
    "E36", ["E36-S01"], """
## Context
This is US-RULE-004 proper: the page at `/rules/:ruleId/form` that composes the row components into a rule, validates it against the IR schema on the server, and saves versions. It also carries US-RULE-007's scope chip and the safety framing that makes authoring an order-placing automation deliberate rather than casual.

Screen contract: `docs/plan/14-screens-catalogue.md` SCR-081 (layout, states, validation messages, hotkeys, audit events, performance). Components: CMP-145 RuleFormEditor composing CMP-140..144, CMP-157, CMP-158, CMP-233 RuleOptions, CMP-234 ValidationPanel, CMP-235 EditorModeToggle, CMP-008, CMP-009.

## Scope / Deliverables
- Route `/rules/:ruleId/form` plus `/rules/new` draft creation; RBAC — `owner` and `manager` with `rules:author`, `viewer` denied (route hidden, 403 from the API surfaced as an explanatory page).
- **CMP-145 RuleFormEditor** organism: Scope → Trigger → Conditions → Actions → Options → action bar (`Validate`, `Simulate` (link-out to SCR-084, E35), `Save draft`, `Arm…` (link-out to SCR-085, E35)).
- **CMP-233 RuleOptions**: name, priority, cooldown seconds, run-once-per-position, max fires per day, ratchet ("only tighten stops"), declared conflicts listed in text with links.
- **CMP-234 ValidationPanel**: `role="log"`, errors first, each entry a button that moves focus to the offending row; error count announced on every recompile; diagnostics come from `POST /api/v1/rules/validate` so the form and the graph report identical results.
- Save path: `POST /api/v1/rules` for a new rule (always stored as version 1, `mode: "disabled"`), `PUT /api/v1/rules/{ruleId}` for an update (creates a new `rule_versions` row); optimistic-concurrency conflict rendered as the "another editor/session saved over your version" error with reload-and-reapply, **never last-writer-wins** (US-RULE-006).
- Editing an armed rule: blocked inline — the user must either disarm or explicitly choose "edit as a new draft version", so the running version cannot mutate under the runtime.
- Live WS `rules` subscription (`rule_ids: [ruleId]`) to reflect external mode changes and the engine-down state.
- States: draft · validating · valid · invalid · armed · vocabulary-unavailable (engine offline, editor read-only with an explanatory banner).
- Validation/safety copy exactly as the handoff pack specifies, including the estimated-detector warning banner, the `flatten_all_positions` "I understand" checkbox, "a rule with no action cannot be saved", and the persistent CMP-158 notice.
- The scope chip in the rule header ("2 accounts · BTCUSDT · new positions") and the plain-language rule summary rendered from `rule-editor-core.summarise` and wired as the rule's accessible description.
- Hotkeys: `Ctrl+S` save draft, `Ctrl+Enter` validate, `Alt+G` switch to graph (E37; until E37 lands, the toggle is present and disabled with a reason), `Alt+↑/↓` reorder, `Ctrl+D` duplicate row — every one also reachable as a visible control.

## Out of scope
The round-trip indicator and the IR inspector (E36-S03). Templates (S04), list (S05), import/export (S06). Simulation, arming, conflict resolution and fire history — E35's surfaces; this page only links to them. Graph editor (E37).

## Acceptance criteria
```gherkin
Scenario: Build and save a rule
  Given a new draft with condition "unrealized_r_multiple >= 1" and action "move_to_breakeven offset=+fees"
  When I press Save draft
  Then POST /api/v1/rules stores it as version 1 in mode "disabled", the plain-language summary reads back the rule, and rule.created is audited
Scenario: Grouped logic is explicit and preserved
  When I create A AND (B OR C) using the grouping controls
  Then the grouping is visible in the UI, the compiled IR contains the same structure, and reopening the rule shows the identical grouping
Scenario: Saving is blocked with an actionable message (failure)
  Given a condition referencing a metric with no data source
  When I attempt to save
  Then the save is refused, the ValidationPanel names the offending row, focusing the entry moves focus to that row, and the message states what to do
Scenario: Concurrent save is refused (error)
  Given another session saved a newer version of this rule
  When I save
  Then an optimistic-concurrency error names the other editor and session and offers reload-and-reapply, and my edits are not silently discarded
Scenario: An armed rule cannot mutate underneath the runtime (edge)
  Given the rule is armed
  When I edit any field
  Then I must either disarm or choose "edit as a new draft version" before the change can be saved
Scenario: Engine offline (failure)
  Given GET /api/v1/rules/vocabulary is unreachable
  Then the editor renders read-only with a banner explaining that the vocabulary is unavailable, and saving is blocked rather than saving a rule built against a guessed vocabulary
Scenario: Order-placing actions require a permitted account (security)
  Given a scope whose accounts do not permit trading
  When an action place_order is added
  Then saving is refused client-side with the reason, and a crafted API request is rejected with 403
```

## Technical notes / design
- Validation is debounced 300 ms and cancels in-flight requests; the last response wins by request id. Compile/round-trip runs on save and on mode switch only (S03 owns it).
- The form never mutates opaque regions; they render via S03's read-only summary card. Save always sends the document produced by `formToIr`, i.e. a structural clone of the loaded IR with form-owned nodes replaced.
- Error codes: `rule_ir_invalid` renders as a blocking panel entry naming the failing JSON path; 403 renders the RBAC explanation; 409 renders the concurrency flow.
- WS subscription options per `23-ws-protocol.md` §15.6 (`rule_ids`, `include_events: false` here — the fire log is SCR-087).

## Test plan
Unit: composition state machine (draft/validating/valid/invalid/armed/vocabulary-unavailable), debounce and race handling, hotkey mapping with focus suppression inside text inputs, duplicate/reorder, opaque-region pass-through on save. Contract: `POST /rules`, `PUT /rules/{ruleId}`, `POST /rules/validate` against `22-api-openapi.yaml`. Integration with a mock WS emitting a mode change. E2E (Playwright, extended in E36-Q02): author-validate-save happy path, invalid-save path, concurrency conflict, armed-edit path. axe on every state. Coverage ≥80 % frontend.

## Security notes
STRIDE (see E36-X01): elevation of privilege via scope — enforced server-side and asserted by E36-X02's scope tests; tampering — the client sends an IR the server re-validates and re-canonicalises, so nothing the client asserts is trusted; repudiation — `rule.saved`, `rule.validated` and `rule.created` are audited with actor and version. Rule content is internal-confidential. Security review label required.

## Accessibility notes
The D04 acceptance list is the gate: labelled condition groups, error summary with in-page links, `role="log"` validation panel with polite announcements, focus-to-anchor as the keyboard mechanism for reaching a diagnostic, visible focus throughout, full keyboard authoring with no drag, plain-language summary as the rule's accessible description, and CMP-158 always present.

## Performance notes
Validation round-trip ≤300 ms p95 (SCR-081); the editor stays interactive during validation; typing latency unaffected by validation (work is off the keystroke path); rendering a 12-condition/6-action rule stays within frame budget (`06-performance-and-load-standard.md`).

## Observability
Audit: `rule.created`, `rule.saved`, `rule.validated`. Metrics: validation latency histogram, validation-error rate, save-conflict counter. Logs: structured client error report on a failed save with the rule id and error code (never the rule body).

## Definition of Done
Route shipped behind the existing rules RBAC; all seven acceptance scenarios automated; coverage floor met; axe green plus one manual screen-reader pass recorded; design QA (E36-D06) blockers closed; `14-screens-catalogue.md` SCR-081 reconciled with shipped behaviour; two approvals incl. code owner; QA sign-off from E36-Q05.

## Dependencies
`blocked_by`: **E36-S01** (the row components). Relies on E35's `/rules/validate`, `/rules/vocabulary` and the rules CRUD surface, and on E09 for RBAC and E28 for account/trade-group references.

## Branch
`feat/rule-form-editor-page`. Expect 3 PRs: composition, save/version flow, states+copy.

## References
`docs/plan/11-user-stories.md` US-RULE-004, US-RULE-006, US-RULE-007 · `docs/plan/14-screens-catalogue.md` SCR-081 · `docs/plan/15-component-catalogue.md` CMP-145, CMP-233, CMP-234, CMP-235 · `docs/plan/22-api-openapi.yaml` · `docs/plan/23-ws-protocol.md` §15.6 · `docs/plan/21-database-schema.md` §3.4.
""")

add("E36-S03", "Story", "Ship the round-trip indicator, graph-only read-only rendering and SCR-088 IR inspector",
    ["type/feature", AREA, "priority/p0", "a11y"], "web", "Sprint 17", "P0 Critical", "Development", "R4 Script sandbox", 3,
    "E36", ["E36-S02"], """
## Context
Owner decision #11 makes form↔graph equivalence a release-blocking product property (US-RULE-001, US-RULE-006), and `11-user-stories.md` states the hash comparison "runs in production, not only in tests". This story implements the form side of that guarantee: the four-state round-trip indicator on SCR-081, the in-place read-only rendering of graph-only constructs, and SCR-088, the drawer that shows the canonical IR and the diff used when the two representations disagree.

## Scope / Deliverables
- **Round-trip indicator** in the SCR-081 header, driven by `POST /api/v1/rules/{ruleId}/compile` on save and on editor-mode switch, with the four designed states:
  1. `Round-trips ✓` — compiled form IR hash equals the stored representation's hash.
  2. `Graph-only construct — read-only here` — amber + glyph + **text**; the affected part renders in place as a read-only summary card reading "Authored in the graph editor: <plain-language summary>. Open in the graph editor to change this." with a link to SCR-082; the rest stays editable.
  3. `Round-trip mismatch` — blocking; save and arm disabled; the diff is shown via SCR-088's diff renderer naming the diverging row/node; exactly two recovery choices, each restating what is lost: "Keep the form version (the graph layout will be regenerated)" and "Keep the graph version (discard form edits)". Never auto-resolved.
  4. `Not verified` — compile service unreachable; draft-save permitted, arming blocked, stated in text.
- **Opaque-region rendering**: read-only summary cards from `rule-editor-core`'s `OpaqueRegion`, with the guarantee that saving the editable parts does not drop or rewrite them (an explicit acceptance test per SCR-081).
- **SCR-088 Rule IR inspector** drawer: read-only canonical IR (CMP-068 CopyableCodeBlock, CMP-033 CopyButton, CMP-046 Drawer, CMP-234 ValidationPanel), version and compiler-version stamps, the diff view, a structured expandable-tree alternative for screen-reader navigation, a `<pre>` region with a described-by note, the compile-failure state naming the offending row/node, and syntax highlighting in a worker for documents over 100 KB.
- Quarantine handling: an IR that fails schema validation on load renders the rule read-only and force-disarmed, names the failing JSON path, and offers export-as-JSON for support (US-RULE-001) — never partially edited.
- Telemetry: `rule.roundtrip_verified {result: identical|graph_only_construct|mismatch|unverified}` and `rule.roundtrip_mismatch_resolved {choice}` as **audited** events; a mismatch also emits a high-severity telemetry event (US-RULE-006).

## Out of scope
Computing the canonical hash or the diff semantics (E35 owns `/compile` and canonicalisation). The graph side of the indicator (E37). Migration logic (E35).

## Acceptance criteria
```gherkin
Scenario: A clean rule reports round-trip
  Given a rule fully representable in the form
  When it is saved
  Then POST /rules/{ruleId}/compile is called once, the indicator reads "Round-trips ✓" in text, and rule.roundtrip_verified is audited with result "identical"
Scenario: Graph-only construct is read-only but preserved
  Given a stored IR whose metric node fans out into two actions
  When the rule is opened in the form editor, an unrelated threshold is edited and saved
  Then the affected part renders as a read-only summary card with a link to the graph editor, and the saved IR contains that sub-tree byte-identically
Scenario: Mismatch blocks saving (failure)
  Given the form representation and the stored graph representation compile to different IR
  Then saving and arming are disabled, the diff names the diverging row, both recovery choices state what is lost, and nothing is auto-resolved
Scenario: Compile service unreachable (error)
  Given POST /rules/{ruleId}/compile times out
  Then the indicator reads "Not verified" in text, draft-save is allowed, arming is blocked, and the reason is stated
Scenario: Quarantined document (error/edge)
  Given a stored IR that fails schema validation
  Then the rule opens read-only and force-disarmed, the failing JSON path is named, export-as-JSON is offered, and no partial edit is possible
Scenario: The IR is navigable by screen reader (a11y)
  Given the SCR-088 drawer
  Then a structured expandable tree equivalent of the JSON is available and the pre region is described as read-only canonical JSON
```

## Technical notes / design
- The client never computes a hash; it compares the `ir_hash` values the server returns for the form-compiled and stored representations. All four states derive from one compile response plus its error mode, so the state machine is `identical | graph_only | mismatch | unverified` and has no other branches.
- Compile is invoked on save and on mode switch only; the indicator shows an explicit "checking…" and "stale" treatment between the last edit and the next compile, so it is never silently out of date.
- The diff renderer works on canonical JSON with a stable line-oriented diff; large documents render lazily.

## Test plan
Unit: the four-state machine incl. timeout, 5xx and `rule_ir_invalid`; opaque-region preservation (deep-equality of the sub-tree after a save); worker highlighting threshold. Contract: `POST /rules/{ruleId}/compile` request/response against `22-api-openapi.yaml`. E2E: the byte-identity acceptance test ("save the editable parts, assert the graph-only sub-tree is unchanged") and the blocking-mismatch path with a fixture whose representations deliberately diverge. Perf: compile + diff ≤500 ms p95 on the 100-node fixture. axe on the drawer and the indicator. Coverage ≥80 %.

## Security notes
The IR inspector must render JSON as text only — never HTML, never a template evaluated in the page. Export-as-JSON from a quarantined rule goes through the same scope-stripping as SCR-089 so a support bundle carries no account bindings. `rule.roundtrip_mismatch_resolved` is audited because resolving a mismatch can change what an armed rule does.

## Accessibility notes
None of the four indicator states may be colour-only — each carries a glyph and text. The mismatch diff is reachable and navigable by keyboard with the diverging row focusable. The `<pre>` IR has a described-by note and an expandable-tree alternative. State changes announce politely; the blocking mismatch announces assertively.

## Performance notes
Compile + round-trip diff ≤500 ms p95 for a 100-node rule (SCR-081); syntax highlighting off the main thread above 100 KB (SCR-088); the indicator never blocks typing.

## Observability
Audited: `rule.roundtrip_verified`, `rule.roundtrip_mismatch_resolved`. Analytics: `rule.ir_viewed`, `rule.ir_copied`. Metric: `rule_editor_roundtrip_result_total{result}` — a non-zero `mismatch` rate in production is an alertable condition owned by the rule-engine team.

## Definition of Done
All six scenarios automated; the byte-identity test is part of the required checks (it is an exit criterion of R3, roadmap §7.3 item 5); axe green; docs reconciled; two approvals incl. code owner; security review comment recorded.

## Dependencies
`blocked_by`: **E36-S02**. Relies on E35's `/rules/{ruleId}/compile`, canonicalisation and hashing.

## Branch
`feat/rule-form-roundtrip`. Two PRs: indicator + opaque regions; IR inspector drawer.

## References
`docs/plan/11-user-stories.md` US-RULE-001, US-RULE-006 · `docs/plan/14-screens-catalogue.md` SCR-081 (round-trip verification UI), SCR-088 · `docs/plan/15-component-catalogue.md` CMP-234, CMP-235, CMP-068 · `docs/plan/22-api-openapi.yaml` · `docs/plan/30-release-roadmap.md` §7.3.
""")

add("E36-S04", "Story", "Ship SCR-083 rule templates gallery with the twelve catalogue templates",
    ["type/feature", AREA, "priority/p1", "a11y"], "web", "Sprint 17", "P1 High", "Development", "R9 Advice boundary", 2,
    "E36", ["E36-S02"], """
## Context
The roadmap names templates as core E36 scope ("templates for common patterns (move-SL-to-BE at R:R, trail by ATR, time-based flatten, daily-loss lockout)") and SCR-080's empty state is "No rules yet — start from a template". Templates are how a rule author gets a correct, safe starting point instead of an empty condition list, and they are the main place where the *(estimated)*-detector and "this is not advice" framing must land (US-RULE-004, risk R9).

## Scope / Deliverables
- Modal SCR-083 with the twelve templates the catalogue lists: move SL to break-even after 1R · ATR trailing stop (ratchet) · structure (swing) trailing stop · partial TP ladder at 1R/2R/3R · time stop (close after N minutes) · cancel working orders when spread > N bps · daily loss lockout · halt on tape-speed spike · avoid stops inside a detected liquidity cluster *(estimated)* · reduce leverage when funding exceeds a threshold · flatten before funding settlement · re-arm chase when the book thins.
- Each card shows: plain-language behaviour text, the metrics it needs, its recorded-history requirement, an explicit *(estimated)*-detector badge where applicable, and which editor it opens in.
- Search/filter, preview-before-instantiate (the compiled IR preview and the plain-language summary), and an empty/no-results state.
- Template definitions live as **static bundled IR documents** validated in CI against the IR schema, so a template can never instantiate an invalid rule.
- Instantiation creates a draft rule (`POST /api/v1/rules`, `mode: "disabled"`) pre-filled with the template's IR and opens SCR-081; nothing evaluates until armed.
- Templates whose metrics are unavailable for the chosen symbol show the missing dependency and the one-click start-recording action rather than silently producing a rule that can never fire.

## Out of scope
Authoring/editing templates in-product (not in scope for v1 — templates are bundled). Arming (E35/SCR-085). Node-editor templates (E37).

## Acceptance criteria
```gherkin
Scenario: Instantiate a template
  When I choose "Move SL to break-even after 1R" and confirm
  Then a draft rule is created in mode "disabled" within 300 ms, SCR-081 opens pre-filled, and rule.created is audited alongside the analytics event rule.template_instantiated
Scenario: Estimated dependence is stated before I commit
  Given the "avoid stops inside a detected liquidity cluster" template
  Then the card and the preview both state in text that it depends on an estimated detector, and the resulting rule carries the same badge
Scenario: Missing data dependency (failure)
  Given a template needing recorded data the selected symbol lacks
  Then the card states the missing dependency and offers a one-click action to start recording, and instantiation is still permitted but the resulting rule is marked as unable to fire until data exists
Scenario: Templates are always valid (edge)
  Given the CI job that validates every bundled template against POST /rules/validate
  Then a template that fails validation fails the build
Scenario: Keyboard and screen reader
  Then the gallery is a list where each card has an accessible name, a plain-language description and its badges read as text, and the whole flow is operable by keyboard
```

## Technical notes / design
Template IR documents live under `apps/web/src/features/rules/templates/*.json` with a manifest carrying id, title, description, required metrics, required history window, estimated-detector flag and target editor. A CI step posts each to `/rules/validate` against a running API fixture; a validation error fails the build. Parameter placeholders (N minutes, N bps, ATR multiple) are declared in the manifest and prompted in the preview before instantiation.

## Test plan
Unit: manifest parsing, search/filter, parameter prompting, badge derivation. Integration: instantiation creates the expected IR. CI contract job: all twelve templates validate. E2E: instantiate three templates end to end and save. axe on the modal. Visual regression on the card grid and empty state. Coverage ≥80 %.

## Security notes
Templates are code-reviewed content: a template that places orders is a pre-built automation, so every template's action list is reviewed in E36-X02's abuse-case review; templates may not reference accounts or symbols, only the scope the user picks afterwards. Advice-boundary (R9): card copy describes mechanics, never expected profitability, and carries no performance claims.

## Accessibility notes
Cards as a list with accessible names; badges as text ("Uses an estimated detector", "Opens in the form editor"); the modal follows the CMP-043 dialog pattern with focus trap and Esc dismissal; preview content reachable by keyboard.

## Performance notes
Template instantiation ≤300 ms with no evaluation until armed (SCR-083); templates are static bundled definitions, so the gallery opens without a network round trip apart from validation preview.

## Observability
Analytics: `rule.template_previewed`, `rule.template_instantiated {templateId}`. Audit: the resulting `rule.created`.

## Definition of Done
Twelve templates shipped and CI-validated; all five scenarios automated; axe green; copy matches the handoff deck; `14-screens-catalogue.md` SCR-083 reconciled; two approvals incl. code owner.

## Dependencies
`blocked_by`: **E36-S02** (templates open into the editor). Template IR shapes depend on E35's vocabulary.

## Branch
`feat/rule-templates-gallery`.

## References
`docs/plan/14-screens-catalogue.md` SCR-083 · `docs/plan/11-user-stories.md` US-RULE-004 · `docs/plan/30-release-roadmap.md` §7.2 (E36) · `docs/plan/32-risk-register.md` R9.
""")

add("E36-S05", "Story", "Ship SCR-080 rules list with filtering, bulk disarm and live state",
    ["type/feature", AREA, "priority/p1", "a11y", "perf"], "web", "Sprint 17", "P1 High", "Development", "R5 Scope", 3,
    "E36", ["E36-S02"], """
## Context
SCR-080 at `/rules` is the entry point to everything the rule engine does and the only place a user sees, before arming, that two rules target the same position (US-RULE-011's surface warning; the resolver itself is E35's SCR-086). It also carries the engine-down banner that tells a trader their armed rules are not evaluating — a safety-relevant statement.

## Scope / Deliverables
- Route `/rules`; RBAC `owner`, `manager` with `rules:author`; `viewer` denied (route hidden, 403).
- Virtualised table (CMP-049 + CMP-155 RuleListRow) with columns: name, scope, trigger summary, armed state, environment, last fired, author, version, fire count.
- Live state from WS topic `rules` (`RuleUpdate`, `23-ws-protocol.md` §15.6) updating armed state and fire counts in place; initial page from `GET /api/v1/rules` with `mode` and `scope` filters.
- Filters (CMP-055 FilterBar) by scope, account, environment and armed state, plus search.
- Row menu: edit form / edit graph / duplicate / simulate / arm / disarm / export / delete / view fire history — each linking to the owning screen (SCR-081, SCR-082, SCR-084, SCR-085, SCR-087, SCR-089).
- Bulk disarm with a confirmation naming exactly which rules will be disarmed.
- CMP-159 RuleConflictWarning banner ("! 2 rules target the same position — resolve precedence", `role="status"`) linking to SCR-086; conflicts come from the server, computed at save and arm time.
- Engine-down banner: "The rule engine is not running — armed rules are not evaluating. Native stops are unaffected." driven by the `system` WS topic.
- Empty state (CMP-026) linking to the templates gallery; loading and error states.
- Rules depending on estimated detectors flagged in the list.

## Out of scope
Arming, disarming semantics and conflict resolution logic (E35/E39 own the endpoints; this screen calls them). Fire history content (SCR-087, E35).

## Acceptance criteria
```gherkin
Scenario: Live armed state
  Given a rule is armed from another session
  When the rules topic publishes the update
  Then the row's state changes in place without a refetch and the state is rendered as text plus icon, never colour alone
Scenario: Conflict is visible before arming
  Given two armed rules that target the same position
  Then a role="status" banner states the conflict and links to the resolver
Scenario: Bulk disarm is explicit (edge)
  Given three selected rules of which one is live-armed
  When bulk disarm is confirmed
  Then the confirmation names each rule and its environment before proceeding, and each disarm is audited separately
Scenario: Engine down (failure)
  Given the rule engine is not running
  Then the banner states that armed rules are not evaluating and that native stops are unaffected, and arming actions are disabled with that reason
Scenario: A viewer cannot reach the page (security)
  Given a user with the viewer role
  Then the route is hidden in navigation and a direct navigation yields an explained 403 with no rule data in the response
Scenario: 500 rules stay smooth (perf)
  Given a list of 500 rules
  Then scrolling stays within a 4 ms scripting budget per frame and filtering does not refetch the whole list
```

## Technical notes / design
Virtualised rows; WS updates applied by rule id into a normalised store so a burst of updates causes one render. Filters are server-side where the API supports them (`mode`, `scope`) and client-side otherwise, with the distinction documented so filters cannot silently apply to only the loaded page.

## Test plan
Unit: filtering, selection and bulk-action guards, WS update reducer, conflict banner derivation. Contract: `GET /rules` and the `rules` WS payload against `22-api-openapi.yaml` / `23-ws-protocol.md`. E2E: filter, bulk disarm confirmation, row-menu navigation, empty state. Perf: a 500-row fixture measured against the 4 ms budget. axe on all states. Coverage ≥80 %.

## Security notes
The list must only ever show rules within the caller's account grants — the server intersects subscription options with grants (`14-screens-catalogue.md` §0.3); the UI must not attempt its own filtering as a substitute. Delete and bulk disarm are audited per entity. `rule.deleted` requires a confirmation naming the rule.

## Accessibility notes
Table semantics with column headers and sort announcements; armed state as text (`DRAFT`/`ARMED-DEMO`/`ARMED-LIVE`/`PAUSED`/`ERROR`) plus icon; conflict banner `role="status"`; row menus keyboard reachable; bulk selection announced ("3 of 500 selected").

## Performance notes
500 rules render without exceeding 4 ms scripting per frame (SCR-080); WS updates coalesced at the topic's 250 ms cadence (`23-ws-protocol.md` §8.2).

## Observability
Audit: `rule.disarmed`, `rule.deleted`, `rule.exported` (from the row menu). Metrics: list render time, WS update apply time.

## Definition of Done
All six scenarios automated; perf number recorded against the budget; axe green; docs reconciled; two approvals incl. code owner; design QA blockers closed.

## Dependencies
`blocked_by`: **E36-S02** (row menu targets the editor). Relies on E35 for `GET /rules`, conflict detection and the `rules` topic; E39 for the engine/kill-switch state reflected in the banner.

## Branch
`feat/rules-list-screen`.

## References
`docs/plan/14-screens-catalogue.md` SCR-080 · `docs/plan/15-component-catalogue.md` CMP-049, CMP-055, CMP-155, CMP-159 · `docs/plan/23-ws-protocol.md` §15.6, §8.2 · `docs/plan/11-user-stories.md` US-RULE-007, US-RULE-010, US-RULE-011.
""")

add("E36-S06", "Story", "Ship SCR-089 rule import and export with scope stripping and per-rule preview",
    ["type/feature", AREA, "priority/p2", "security"], "web", "Sprint 17", "P2 Medium", "Development", "R13 Sharing abuse", 2,
    "E36", ["E36-S03", "E36-S05"], """
## Context
SCR-089 lets a user move rules between environments and hand one to support. It is the epic's data-egress and data-ingress surface, so it is where sharing abuse (R13) and privilege escalation via a crafted bundle are most plausible. The catalogue's sign-off checklist makes two promises that must be *verified*, not merely stated: an exported bundle never contains account ids, keys or armed state, and imported rules always land disarmed.

## Scope / Deliverables
- Modal SCR-089 with separate, labelled Export and Import sections (CMP-043 Dialog, CMP-067 FileDrop, CMP-068 CopyableCodeBlock, CMP-033 CopyButton, CMP-027 InlineError, CMP-234 ValidationPanel).
- **Export**: single / selected / all; bundle = canonical IR + optional graph layout (`presentation`) + template-level metadata; scope bindings (account ids, trade-group ids), armed state and any key material are stripped, and the UI states this; the stripping is asserted by a test that scans the produced bundle for any UUID matching a known account id.
- **Import**: schema-version check, per-rule accept/skip preview table with reasons, remapping of account/symbol references to what the importing user can access, validation server-side via `POST /api/v1/rules/validate` with per-rule results streamed, and a failure list naming the offending rule and JSON path ("unknown metric or action names are rejected with the offending path named").
- Every imported rule is created disarmed (`mode: "disabled"`), as a new rule (never overwriting an existing one silently), and audited as `rule.imported`.
- Version-mismatch handling: a bundle from an older IR version is migrated by the server on import and the migration is stated per rule; a bundle from a *newer* version is refused with an explanatory message rather than partially imported.

## Out of scope
Workspace/layout import-export (US-LAY-007, its own epic). Sharing rules between users as a first-class feature. Arming after import.

## Acceptance criteria
```gherkin
Scenario: Export strips bindings
  Given three rules scoped to specific accounts
  When they are exported
  Then the bundle contains no account id, no key material and no armed state, the UI states this, and the automated scan for known account identifiers finds none
Scenario: Import lands disarmed
  Given a valid bundle of five rules
  When it is imported
  Then five new rules are created in mode "disabled", none is armed, and rule.imported is audited per rule
Scenario: A crafted bundle cannot grant access (security failure)
  Given a bundle whose scope references an account the importing user cannot trade
  Then that rule is either remapped to a permitted scope or listed as skipped with the reason, and a crafted API request carrying the foreign account is rejected with 403
Scenario: Unknown vocabulary is named, not guessed (error)
  Given a bundle referencing metric "quantum_flux"
  Then the rule is rejected with the offending JSON path named, and no partially-built rule is created
Scenario: Newer schema version (edge)
  Given a bundle declaring an IR version newer than this deployment supports
  Then the import is refused entirely with an explanation, and nothing is created
Scenario: Large bundle (perf)
  Given a 100-rule bundle
  Then validation completes in <=2 s with per-rule results streamed and the UI remains interactive
```

## Technical notes / design
Import is a two-phase flow: validate-all (server) → show preview → create-accepted. Creation is per rule so a partial failure leaves a well-defined set of created rules, each audited; the UI reports exactly which succeeded. File size and nesting-depth limits are enforced before parsing (see E36-T01's parser guards).

## Test plan
Unit: bundle builder and stripper, preview table state, per-rule accept/skip, version gating. Security test: the account-identifier scan over exported bundles; an import fixture with a foreign account id asserting 403/skip. Contract: `POST /rules/validate` and `POST /rules` per rule. E2E: export→import round trip into a second user context, asserting disarmed state and remapped scope. Perf: the 100-rule bundle target. axe on both sections. Coverage ≥80 %.

## Security notes
Primary threats (E36-X01): information disclosure via exported bundles (control: stripping + the automated scan), elevation of privilege via crafted scope (control: server-side remap/reject, 403 on the API), tampering/DoS via a pathological JSON document (control: size and depth limits before parse), repudiation (control: `rule.exported` and `rule.imported` audit events with actor, rule ids and source filename). Requires the `security` review label and sign-off in E36-X03.

## Accessibility notes
Export and import are separate labelled sections; the import preview is a table with per-row status and reason text; every validation failure names the rule and the field in text; file drop has a keyboard-accessible file-picker equivalent; progress is announced politely.

## Performance notes
100-rule bundle validates in ≤2 s with per-rule results streamed (SCR-089); parsing happens off the main thread for bundles over 1 MB.

## Observability
Audit: `rule.exported {ruleIds, count}`, `rule.imported {ruleIds, skipped, reasons}`. Metrics: import success/skip counters, bundle size histogram.

## Definition of Done
All six scenarios automated including the two security tests; axe green; catalogue checklist satisfied; security sign-off recorded in E36-X03; docs reconciled; two approvals incl. code owner and the security code owner.

## Dependencies
`blocked_by`: **E36-S03** (canonical IR rendering and the compile/validate plumbing), **E36-S05** (export is launched from the list's row menu and bulk selection).

## Branch
`feat/rule-import-export`.

## References
`docs/plan/14-screens-catalogue.md` SCR-089 · `docs/plan/11-user-stories.md` US-RULE-001 · `docs/plan/04-security-program.md` · `docs/plan/22-api-openapi.yaml`.
""")

add("E36-T02", "Chore", "Reconcile plan docs, ADR and changelog with the shipped form editor",
    ["type/docs", AREA, "priority/p2"], "docs", "Sprint 17", "P2 Medium", "Development", "None", 1,
    "E36", ["E36-S06", "E36-S04"], """
## Context
`02-definition-of-ready-done.md` §2.2 requires the plan docs to describe the **shipped** behaviour, not the original proposal. E36 will inevitably diverge in small ways — a prop renamed, a grouping limit chosen, a validation message reworded — and E37 plus E40 build directly on these documents, so drift here is expensive.

## Scope / Deliverables
- Update `docs/plan/14-screens-catalogue.md` SCR-080, SCR-081, SCR-083, SCR-088, SCR-089 entries: final states, final copy, final hotkeys, final data calls, Figma links.
- Update `docs/plan/15-component-catalogue.md` CMP-140..145, CMP-155, CMP-157..159, CMP-233..235 with the shipped prop signatures and Storybook story names.
- Update `docs/plan/18-traceability-matrix.md` rows for US-RULE-002, 003, 004, 007 and the form-side of 001/006 with the implementing ticket keys.
- Write **ADR: "The form editor is the accessible equivalent of the node-graph editor"** under `docs/plan/27-adrs/` recording the decision, the boolean-grouping model chosen in E36-D01, the exact list of constructs classified as graph-only, and the consequence that an a11y regression in the form editor blocks E37.
- Developer documentation for `packages/rule-editor-core` (README with the form-model ⇄ IR contract, the opaque-region guarantee, and how to add a parameter renderer when E35 adds an action).
- Changelog entries (semver, `07-release-and-prr.md`) for the rules feature.

## Out of scope
Changing behaviour. Documenting the node editor (E37) or the runtime (E35).

## Acceptance criteria
```gherkin
Scenario: Docs match the build
  Given the shipped SCR-081 and its catalogue entry
  When a reviewer compares them field by field
  Then states, copy, hotkeys and data calls match, or the difference is an intentional, explained note
Scenario: The graph-only construct list is authoritative
  Given the new ADR
  Then it enumerates every construct the form editor renders read-only, and E37 references that list rather than inventing its own
Scenario: Traceability is complete (edge)
  Given the traceability matrix rows for the RULE domain
  Then every Must story this epic covers names its implementing ticket key
Scenario: A prop diverged (failure)
  Given a component whose shipped props differ from the catalogue
  Then the catalogue is corrected in this PR — the code is not changed to match a stale doc without a design decision
```

## Technical notes / design
The ADR follows the existing `27-adrs/` template (context, decision, status, consequences, alternatives considered).

## Test plan
Docs lint/link check in CI; a reviewer from design and one from engineering both approve.

## Security notes
N/A — no code change. Ensure no screenshot or example in the docs contains real account ids.

## Accessibility notes
The ADR records the a11y obligation that E37 inherits; the a11y acceptance list from E36-D04 is linked from the SCR-081 entry.

## Performance notes
Record the measured validation, compile and list-render numbers from E36-Q04 in the catalogue performance notes, replacing the target with the achieved figure where they differ.

## Observability
Document the final audit/analytics event list in the catalogue entries so E41 (journal) and the audit browser (E42) can rely on it.

## Definition of Done
All five documents updated and merged; ADR merged with status Accepted; package README published; changelog entry present; two approvals.

## Dependencies
`blocked_by`: **E36-S06**, **E36-S04** — reconcile once the feature set is final.

## Branch
`chore/rule-form-editor-docs`.

## References
`docs/plan/02-definition-of-ready-done.md` · `docs/plan/07-release-and-prr.md` · `docs/plan/27-adrs/` · `docs/plan/18-traceability-matrix.md`.
""")

json.dump(T, open(os.path.join(os.path.dirname(__file__), "backlog", "_e36_b.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(len(T), sum(t["estimate"] for t in T))
