# -*- coding: utf-8 -*-
import json, io, os

PHASE = "P3 Drawing & Alerts"
MILE = "R3 Trading on demo"
AREA = "area/rule-engine"

T = []

def add(key, kind, title, labels, component, sprint, priority, perspective, risk, estimate, parent, blocked_by, body):
    T.append({
        "key": key, "kind": kind, "title": title, "labels": labels, "component": component,
        "phase": PHASE, "sprint": sprint, "priority": priority, "perspective": perspective,
        "risk": risk, "estimate": estimate, "parent": parent, "blocked_by": blocked_by,
        "milestone": MILE, "body": body.strip() + "\n",
    })

VOCAB_METRICS = ("price, unrealized_r_multiple, unrealized_pnl_pct, realized_pnl_today, position_side, position_open, "
"atr(n), ema(n), swing_low(n), swing_high(n), cvd_divergence, spread_bps, time_in_trade, orderbook_imbalance, "
"funding_rate, iceberg_present_at_level *(estimated)*, distance_to_liquidity_cluster *(estimated)*, "
"in_stop_hunt_zone *(estimated)*, stop_run_detected *(estimated)*, big_trade_notional, tape_speed_zscore, "
"market_regime *(estimated)*, dom_imbalance_ratio, open_interest_delta")
VOCAB_ACTIONS = ("place_order, modify_stop_loss, modify_take_profit, cancel_order, move_to_breakeven, scale_out, "
"scale_in, flatten_all_positions, halt_new_orders, resume_new_orders, send_notification, log_journal_tag, "
"reduce_leverage, widen_stop, arm_chase_limit, start_iceberg_slice")

# ---------------------------------------------------------------- EPIC
epic_body = f"""
## Context
R3 "Trading on demo" (`docs/plan/30-release-roadmap.md` §7) ships the rule engine with **both** editors compiling to **one IR** executed by **one runtime** (roadmap §7.1 goal 3, owner decision OD#11). **E35** owns the IR schema, the compiler, the validator, the vocabulary endpoint and the runtime. **E37** owns the node-graph editor. **E36 — this epic — owns the form / condition-list editor and the non-canvas rule surfaces**: the rules list, the structured editor page, the templates gallery, the read-only IR inspector and rule import/export.

The roadmap scopes E36 as: "Condition-list UI with typed operand pickers, grouping (AND/OR/NOT), templates for common patterns (move-SL-to-BE at R:R, trail by ATR, time-based flatten, daily-loss lockout); inline validation against the IR schema; live preview of the compiled IR; keyboard-complete authoring" — 21 pts, Sprints S16–S17 (`30-release-roadmap.md` §7.2).

Two properties make this epic load-bearing rather than "just a form":
1. **The form editor is the accessible equivalent of the node-graph editor.** `15-component-catalogue.md` CMP-146 declares the always-available "Switch to form view" toggle the *primary accessible-equivalent mechanism* for the canvas, "mandated because free-form 2D graph manipulation cannot be made fully keyboard-equivalent". If the form editor is not 100 % keyboard-operable and screen-reader complete, the node editor cannot ship at all.
2. **The form editor must never lose what the graph editor authored.** `14-screens-catalogue.md` SCR-081 requires that a graph-only construct renders as an in-place read-only summary card and that "saving the editable parts must not drop or rewrite the read-only part — this is an explicit acceptance test" (US-RULE-006).

Nothing in this epic evaluates a rule or places an order. Every semantic decision (what is valid, what the canonical IR is, what the hash is) is delegated to E35's endpoints so that form and graph report *identical* diagnostics for the same IR (CMP-234 data contract).

## Scope / Deliverables
**Stories covered (`docs/plan/11-user-stories.md` §20 RULE):** US-RULE-002 (metric vocabulary, Must — the picker surface), US-RULE-003 (action vocabulary, Must — the action-row surface), US-RULE-004 (form / condition-list editor, Must), US-RULE-007 (rule scoping, Must — the selector and the scope chip), US-RULE-001 / US-RULE-006 **form-side only** (round-trip indicator, graph-only read-only rendering, IR inspector, import/export; the IR, hash and compile service are E35).

**Screens:** SCR-080 Rules list · SCR-081 Rule editor — form mode · SCR-083 Rule templates gallery · SCR-088 Rule IR inspector (advanced) · SCR-089 Rule import / export.

**Components (`15-component-catalogue.md`):** CMP-140 RuleConditionRow, CMP-141 RuleConditionGroup, CMP-142 RuleActionRow, CMP-143 RuleTriggerPicker, CMP-144 RuleScopeSelector, CMP-145 RuleFormEditor, CMP-155 RuleListRow, CMP-157 MetricPickerCombobox, CMP-158 SafetyInvariantNotice, CMP-159 RuleConflictWarning, CMP-233 RuleOptions, CMP-234 ValidationPanel, CMP-235 EditorModeToggle (form side).

**API consumed (`22-api-openapi.yaml`):** `GET /rules`, `POST /rules`, `GET|PUT|DELETE /rules/{{ruleId}}`, `GET /rules/{{ruleId}}/versions`, `GET /rules/{{ruleId}}/versions/{{versionId}}`, `PUT /rules/{{ruleId}}/active-version`, `POST /rules/validate`, `POST /rules/{{ruleId}}/compile`, `GET /rules/vocabulary`, `PUT /rules/{{ruleId}}/mode` (link-out only). **WS:** topic `rules` (`rule_ids`, `include_events`, payload `RuleUpdate`, `23-ws-protocol.md` §15.6). **DB (read via API only):** `rules`, `rule_versions` (`21-database-schema.md` §3.4).

**Package:** `packages/rule-editor-core` (framework-free form model ↔ IR adapter, vocabulary cache, diagnostics anchoring) + `apps/web/src/features/rules/*`.

## Out of scope
- The rule IR schema, canonicalisation, hashing, compiler, validator semantics, vocabulary content and the runtime — **E35**.
- The node-graph canvas, node components CMP-146..153, CMP-236..238, auto-layout, node search — **E37**.
- SCR-084 simulation/backtest panel, SCR-085 arming dialog, SCR-086 conflict resolver, SCR-087 fire history — **E35** (they are runtime surfaces; E36 only renders link-outs and the CMP-159 warning banner fed by E35's conflict API).
- Risk caps, lockouts, kill-switch (US-RULE-012..014) — **E39**. Alerts reusing the condition editor — **E40**.
- Android / any mobile client (owner decision 2026-09-14). Non-Bybit venues.

## Acceptance criteria
```gherkin
Scenario: A rule can be authored end to end without a pointer
  Given a keyboard-only user on /rules
  When they create a rule from the templates gallery, change the metric, operator and value of a condition, add an any-of group, add a move_to_breakeven action, set scope and save
  Then the rule is stored as version 1 in mode "disabled" and every step was reachable by keyboard with an audible screen-reader announcement

Scenario: Graph-authored constructs survive a form save
  Given a rule whose stored IR contains a construct the form editor cannot represent
  When it is opened in the form editor, an editable threshold is changed and the rule is saved
  Then the graph-only sub-tree is byte-identical in the new version and the presentation block is untouched

Scenario: Diagnostics are identical in both editors (failure case)
  Given an IR that fails validation with a type mismatch
  When the same IR is validated from the form editor and from the graph editor
  Then POST /rules/validate returns the same diagnostics and both editors anchor them to the corresponding row/node

Scenario: The editor cannot silently disagree with the server
  Given the compile service is unreachable
  Then the round-trip indicator reads "Not verified" in text, draft-save is allowed and arming is blocked
```

## Technical notes / design
- One-way data flow: the editor owns a **form model**; `rule-editor-core` maps form model ⇄ `RuleIr`; the server is the only authority on validity and on the canonical hash. The editor never computes a hash locally.
- Vocabulary (`GET /rules/vocabulary`) is fetched once per session, cached with an ETag, and drives every picker; an unknown metric/action in a loaded IR renders as a disabled row naming the unknown identifier rather than being dropped.
- Validation is debounced (300 ms) on edit; compile + round-trip check runs **on save and on mode switch only** (SCR-081 performance note), never per keystroke.
- Error codes surfaced verbatim from the API problem catalogue, incl. `rule_ir_invalid` (`22-api-openapi.yaml` §error catalogue) and optimistic-concurrency conflicts on `PUT /rules/{{ruleId}}`.

## Test plan
Unit (≥80 % FE lines) on `rule-editor-core` mapping and on every component; contract tests against `22-api-openapi.yaml` for the six rules endpoints used; Playwright E2E for authoring, templates, import/export and the graph-only read-only case; axe-core in CI plus a manual NVDA/VoiceOver pass; perf assertions for the 500-row virtualised list and the ≤300 ms validation round-trip. Fixtures: a corpus of ≥30 rule IR documents shared with E35's round-trip corpus (roadmap §7.3 exit criterion 5).

## Security notes
Threats (STRIDE, `04-security-program.md`): tampering with an imported rule bundle to smuggle actions or account references; elevation of privilege by authoring a rule scoped to an account the user cannot trade; information disclosure through exported bundles (bundles must never contain account ids, keys or armed state — SCR-089); repudiation if rule edits are not audited. Controls: server-side scope intersection, `rules:write` enforcement, import remapping with per-rule accept/skip, audit events `rule.created|updated|exported|imported`.

## Accessibility notes
WCAG 2.2 AA (`05-accessibility-standard.md`). The form editor is a named a11y-critical surface: every condition row is a labelled group ("Condition 1 of 3"), validation errors are summarised with in-page links, no operation requires drag, and the plain-language rule summary is the accessible description of the rule (US-RULE-004 NFR).

## Performance notes
`06-performance-and-load-standard.md`: validation round-trip ≤300 ms; compile + round-trip diff ≤500 ms p95 for a 100-node rule; the rules list renders 500 rows within a 4 ms scripting budget per frame; template instantiation ≤300 ms.

## Observability
Audit: `rule.created`, `rule.updated`, `rule.saved`, `rule.validated`, `rule.roundtrip_verified {{result}}`, `rule.roundtrip_mismatch_resolved {{choice}}`, `rule.exported`, `rule.imported`. Analytics: `rule.template_previewed`, `rule.template_instantiated`, `rule.ir_viewed`, `rule.ir_copied`. Frontend metrics: validation latency histogram, compile latency histogram, editor error-rate.

## Definition of Done
Per `02-definition-of-ready-done.md` §2.2: all children Done; coverage floors held; SCR-080/081/083/088/089 designs signed off ≥2 sprints ahead; axe-core green + manual SR pass; STRIDE findings closed; QA epic-level regression recorded; Owner demo accepted; `14-screens-catalogue.md`, `15-component-catalogue.md` and `18-traceability-matrix.md` reconciled with shipped behaviour.

## Dependencies
`blocked_by`: **E35** (IR, vocabulary, validate/compile endpoints — nothing here can be built against a moving IR), **E09** (auth, sessions, RBAC `rules:read`/`rules:write`), **E28** (account/trade-group references used by CMP-144 scope selector). E37 is blocked *by* this epic.

## Children
```mermaid
graph TD
  D01[E36-D01 UX research] --> D02[E36-D02 Hi-fi SCR-081/083]
  D01 --> D03[E36-D03 Hi-fi SCR-080/088/089 + DS]
  D02 --> D04[E36-D04 A11y design review]
  D03 --> D04
  D04 --> D05[E36-D05 Handoff pack]
  D05 --> T01[E36-T01 rule-editor-core]
  T01 --> S01[E36-S01 Condition & action rows]
  S01 --> S02[E36-S02 SCR-081 editor page]
  S02 --> S03[E36-S03 Round-trip indicator + SCR-088]
  S02 --> S04[E36-S04 SCR-083 templates]
  S02 --> S05[E36-S05 SCR-080 rules list]
  S03 --> S06[E36-S06 SCR-089 import/export]
  S05 --> S06
  S06 --> T02[E36-T02 Docs & ADR reconciliation]
  S02 --> D06[E36-D06 Design QA]
  S01 --> Q01[E36-Q01 Test plan]
  Q01 --> Q02[E36-Q02 E2E suite]
  Q01 --> Q03[E36-Q03 A11y audit]
  Q01 --> Q04[E36-Q04 Perf scripts]
  Q02 --> Q05[E36-Q05 Exploratory + sign-off]
  X01[E36-X01 STRIDE] --> X02[E36-X02 Abuse cases & scope assertions]
  X02 --> X03[E36-X03 Security sign-off]
  S06 --> X03
  Q05 --> X03
```

## Risks
R5 Scope (the vocabulary is large and grows with detectors — mitigated by rendering entirely from `GET /rules/vocabulary`), R4 Script sandbox (an authoring surface for automated order placement is an abuse vector — mitigated by X01/X02), R9 Advice boundary (templates must not read as trading advice — mitigated by plain-language behaviour text and the *(estimated)* badging), R14 User retention (an unusable authoring surface pushes users to the canvas, which is the less accessible path).

## Branch
`feat/rule-form-editor-<short>` per ticket; PRs ≤400 LOC.

## References
`docs/plan/11-user-stories.md` §20 · `docs/plan/14-screens-catalogue.md` §6 · `docs/plan/15-component-catalogue.md` §5, §7A · `docs/plan/18-traceability-matrix.md` · `docs/plan/22-api-openapi.yaml` (rules tag) · `docs/plan/23-ws-protocol.md` §15.6 · `docs/plan/21-database-schema.md` §3.4 · `docs/plan/24-internal-schemas.md` §11 · `docs/plan/30-release-roadmap.md` §7 · `docs/plan/05-accessibility-standard.md` · `docs/plan/06-performance-and-load-standard.md`.
"""
add("E36", "Epic", "Rule form editor",
    ["type/feature", AREA, "priority/p0", "design", "qa", "security", "a11y", "perf"],
    "web", "Sprint 16", "P0 Critical", "Architecture", "R5 Scope", 62, None,
    ["E35", "E09", "E28"], epic_body)

# ---------------------------------------------------------------- DESIGN
add("E36-D01", "Task", "UX research: how a trader expresses a stop-management rule in words",
    ["type/design", AREA, "priority/p1", "design", "ux-research"], "web", "Sprint 13", "P1 High", "Product", "R14 User retention", 3,
    "E36", ["E35"], f"""
## Context
E36 introduces the non-canvas authoring path for rules (SCR-081) and it must be good enough that nobody is *forced* onto the node canvas — `15-component-catalogue.md` CMP-146 makes the form view the mandated accessible equivalent of the graph. Before any pixels are drawn we need to know how the Owner and the account-manager personas (`docs/plan/10-personas.md`, persona mode **M1 Rule-author**) actually phrase the rules they already run by hand: "move my stop to break-even once I'm up 1R", "trail two ATRs but never loosen".

The vocabulary is fixed and large ({VOCAB_METRICS.count(',')+1} metrics, {VOCAB_ACTIONS.count(',')+1} actions — `14-screens-catalogue.md` SCR-081). The open question is not *what* is available but *how it should be grouped, named and defaulted* so that a rule reads back as a sentence rather than as a query builder.

## Scope / Deliverables
- 5 semi-structured sessions (Owner + managers, 45 min) capturing verbatim the last five rules each person ran manually, and how they would express them.
- A card-sort of the metric vocabulary (the 24 metrics listed on SCR-081) producing the category set for CMP-157 `category` prop (`price | position | orderflow | risk | detector`) — confirm or replace it with evidence.
- A comprehension test of the plain-language rule summary: show three summaries, ask what the rule does; target ≥4/5 correct.
- A decision on grouping UX: nested groups vs a flat "all of / any of" with one nesting level (SCR-081 shows "+ any-of group"); record the chosen model and its limits, because this decides which constructs become "graph-only".
- A decision on *(estimated)* framing: where the badge must appear (picker option, condition row, rule summary, list row, arming dialog) so it is never lost — US-RULE-002 requires it in picker and summary at minimum.
- Findings deck + a one-page "authoring principles" note that D02/D03 are held against; any resulting update to `docs/plan/10-personas.md` and `docs/plan/13-user-flows.md` F10.

## Out of scope
Hi-fi visual work (D02/D03). Node-canvas research (E37). Usability testing of built software (E36-Q05). Changing the vocabulary itself (E35 owns it — research may only recommend).

## Acceptance criteria
```gherkin
Scenario: The grouping model is decided with evidence
  Given at least five research sessions and a card sort
  When findings are published
  Then the chosen boolean-grouping model is stated with the participant evidence behind it, and the constructs it cannot express are listed explicitly as future "graph-only" constructs
Scenario: Plain-language summary comprehension is measured
  Given three candidate rule summaries
  When participants are asked to state what each rule does
  Then comprehension is ≥4/5 per summary, or the summary grammar is revised and retested
Scenario: Estimated-detector framing is settled (edge)
  Given a rule using in_stop_hunt_zone
  Then research states every surface on which the "(estimated)" badge must appear, and CDO sign-off is recorded on that list
Scenario: No participant available (failure)
  Given fewer than three participants can be scheduled inside the sprint
  Then the ticket is not silently closed: the gap is recorded on the ticket, D02 proceeds under an explicit CDO waiver, and a follow-up validation is scheduled against the built editor in E36-Q05
```

## Technical notes / design
Sessions recorded and transcribed; card sort run in whatever tool the design org already uses; analysis as an affinity map. The deliverable is a note under `docs/plan/` linked from the SCR-081 catalogue entry, not a slide deck only.

## Test plan
N/A (research). Validation is the comprehension threshold above and the later usability pass in E36-Q05.

## Security notes
Session recordings contain account and PnL talk — treat as confidential, store in the design org's restricted space, redact account identifiers in the published deck. Data classification: internal-confidential.

## Accessibility notes
At least one session with a keyboard-only / screen-reader participant or, failing that, with the accessibility specialist acting as proxy, because the form editor is the mandated accessible alternative to the canvas.

## Performance notes
N/A.

## Observability
N/A.

## Definition of Done
Findings note merged under `docs/plan/`; the four decisions (categories, grouping model, summary grammar, estimated-badge surfaces) recorded; CDO sign-off comment on the ticket; D02/D03 linked as consumers; personas/flows updated if changed.

## Dependencies
`blocked_by`: **E35** — the vocabulary and IR shape must be at least draft-stable before we research how to present them.

## Branch
`design/rule-form-research` (docs only).

## References
`docs/plan/10-personas.md` · `docs/plan/11-user-stories.md` US-RULE-002..004 · `docs/plan/14-screens-catalogue.md` SCR-081, SCR-083 · `docs/plan/15-component-catalogue.md` CMP-140/141/157 · `docs/plan/16-design-system-brief.md`.
""")

add("E36-D02", "Task", "Wireframe to hi-fi: SCR-081 form editor and SCR-083 templates gallery",
    ["type/design", AREA, "priority/p0", "design"], "web", "Sprint 14", "P0 Critical", "Product", "R5 Scope", 5,
    "E36", ["E36-D01"], f"""
## Context
SCR-081 (rule editor, form mode) is the primary authoring surface of the rule engine and the accessible equivalent of the node canvas; SCR-083 (templates gallery) is how most rules will actually start. Both have ASCII wireframes and a full sign-off checklist in `docs/plan/14-screens-catalogue.md` §6; this ticket turns them into signed-off hi-fi with every state drawn, two sprints ahead of E36-S01/S02 (Sprint 16) per the design-ahead rule in `00-planning-brief.md`.

## Scope / Deliverables
- **SCR-081** hi-fi in Figma covering the full layout (Scope · Trigger · Conditions · Actions · Options · action bar) and every state named in the catalogue: draft · validating · valid · invalid (summary + offending row highlighted and focusable) · armed (edit requires disarm or a new version) · vocabulary-unavailable (engine offline).
- The **round-trip indicator** in all four designed states: `Round-trips ✓`, `Graph-only construct — read-only here` (amber + glyph + text, with the in-place read-only summary card), `Round-trip mismatch` (blocking, with the two named recovery choices and their consequences), `Not verified`.
- Every validation message drawn as designed copy: "Row 2 is missing a value.", "`position_side` compares to long/short, not a number.", the estimated-detector warning banner, the `flatten_all_positions` "I understand" checkbox, "a rule with no action cannot be saved".
- The metric picker (CMP-157) open state with categories, descriptions, units and the *(estimated)* tag rendered **in the option list**; the action row (CMP-142) with per-action parameter forms for at least place_order, modify_stop_loss, move_to_breakeven, scale_out, flatten_all_positions, halt_new_orders.
- The plain-language rule summary block and the scope chip ("2 accounts · BTCUSDT · new positions", US-RULE-007).
- CMP-158 SafetyInvariantNotice placement — persistent, non-dismissible, present in the composition.
- **SCR-083** hi-fi: template cards for all twelve catalogue templates with plain-language behaviour text, required metrics, recorded-history requirement, estimated-detector badge, which editor it opens in, search/filter, preview-before-instantiate, empty/no-results states.
- Density and theming: both screens at the product's compact and comfortable densities, light and dark, at 125 % and 200 % zoom without clipping.

## Out of scope
Node-canvas designs (E37). SCR-080/088/089 (E36-D03). Motion beyond what the DS already defines is specified in D03. Arming dialog SCR-085 and simulate panel SCR-084 (E35).

## Acceptance criteria
```gherkin
Scenario: The catalogue sign-off checklist is satisfied
  Given the SCR-081 design sign-off acceptance checklist in 14-screens-catalogue.md
  When the hi-fi is reviewed
  Then every box is demonstrably drawn — condition rows, grouping, action rows, scope selector, searchable vocabulary picker with descriptions, validation presentation, estimated-detector banner, graph-authored read-only summary, round-trip indicator, keyboard-only authoring annotation, arming path — and the reviewer initials each
Scenario: Every state has a frame
  Given the six named SCR-081 states and the four round-trip indicator states
  Then each exists as its own frame with realistic content, not as a note
Scenario: Long content does not break the layout (edge)
  Given a rule with 12 conditions, 6 actions, a nested any-of group and a 40-character metric name at 200% zoom
  Then the frame shows the intended overflow, wrapping and sticky-action-bar behaviour
Scenario: A blocking mismatch is unambiguous (failure)
  Given the Round-trip mismatch state
  Then saving is visibly disabled, the diff entry point is drawn, and each of the two recovery choices restates in text exactly what will be lost
```

## Technical notes / design
Built from `docs/plan/16-design-system-brief.md` tokens only; any new token or variant is raised in D03 as a design-system contribution rather than being drawn ad hoc. Metric list used in the frames must be exactly: {VOCAB_METRICS}. Action list: {VOCAB_ACTIONS}.

## Test plan
Design review with the Architect (IR representability), a rule-author persona walkthrough of three concrete rules, and a contrast/target-size check with the DS plugin before hand-off.

## Security notes
Frames must not contain real account ids or key material. The `flatten_all_positions` and order-placing actions are drawn in the destructive-action visual class per the safety framing.

## Accessibility notes
Annotate focus order, roles and names for every control; each condition row annotated as a labelled group "Condition N of M"; error summary → in-page link behaviour annotated; contrast ≥4.5:1 for text and ≥3:1 for the amber/blocking indicator states, and none of the four round-trip states may be distinguished by colour alone.

## Performance notes
Annotate that validation is debounced (300 ms) and that the compile/round-trip check runs on save and on mode switch only, so the indicator must have an explicit "stale/checking" treatment.

## Observability
Annotate where `rule.roundtrip_verified` and `rule.template_instantiated` fire, so instrumentation is not invented by engineering.

## Definition of Done
Figma file with all frames, states and annotations; checklist initialled; CDO and Architect sign-off comments; linked from the SCR-081/SCR-083 catalogue entries; Status Done ≥2 sprints before Sprint 16.

## Dependencies
`blocked_by`: **E36-D01** (grouping model, categories, badge surfaces).

## Branch
`design/rule-form-editor-hifi` (docs/Figma links only).

## References
`docs/plan/14-screens-catalogue.md` SCR-081, SCR-083 · `docs/plan/15-component-catalogue.md` CMP-140..145, CMP-157, CMP-158, CMP-233..235 · `docs/plan/16-design-system-brief.md` · `docs/plan/05-accessibility-standard.md`.
""")

add("E36-D03", "Task", "Hi-fi SCR-080, SCR-088, SCR-089 plus rule-editor design-system contributions and motion",
    ["type/design", AREA, "priority/p1", "design"], "web", "Sprint 14", "P1 High", "Product", "R5 Scope", 3,
    "E36", ["E36-D01"], """
## Context
Around the editor itself E36 ships three supporting surfaces: the rules list (SCR-080, the entry point and the only place a conflict warning is surfaced before arming), the IR inspector (SCR-088, the advanced/diagnostic drawer that proves round-trip equivalence), and import/export (SCR-089). Each has its own sign-off checklist in `docs/plan/14-screens-catalogue.md` §6. This ticket also contributes the new/extended design-system entries the rule band needs so nothing is drawn ad hoc.

## Scope / Deliverables
- **SCR-080** hi-fi: virtualised table with the columns the checklist names (name, scope, trigger summary, armed state, environment, last fired, author, version); armed/disarmed/error state as text **plus** icon; filters by scope, account, environment and armed state; bulk disarm with confirmation; row menu (edit form / edit graph / duplicate / simulate / arm / disarm / export / delete / fire history); empty state linking to the templates gallery; estimated-detector flag on dependent rows; the conflict banner ("! 2 rules target the same position — resolve precedence", `role="status"`) and the engine-down banner ("The rule engine is not running — armed rules are not evaluating. Native stops are unaffected.").
- **SCR-088** hi-fi: read-only canonical IR with copy/export, the structured expandable-tree screen-reader alternative, the round-trip diff view, version + compiler-version stamps, the advanced/diagnostic labelling, and the compile-failure state naming the offending row/node.
- **SCR-089** hi-fi: export selection (single / selected / all) with the scope-stripping note; the explicit statement (and its verification) that a bundle never contains account ids, keys or armed state; import file drop, per-rule accept/skip preview table with reasons, version-mismatch handling, validation-failure list naming rule and field, and the "imported rules always land disarmed" statement.
- **Design-system contributions:** entries/variants for CMP-140, CMP-141 (`space.rulegroup.indent`), CMP-142, CMP-143, CMP-144, CMP-155, CMP-157, CMP-158, CMP-159, CMP-233, CMP-234, CMP-235; any new token proposed formally against `docs/plan/16-design-system-brief.md` with a rationale.
- **Motion spec:** row add/remove and reorder in the condition list, group expand/collapse, validation panel error-count change, round-trip indicator state transition, drawer open/close — all with `prefers-reduced-motion` fallbacks and durations from the DS motion scale.

## Out of scope
SCR-081/083 (D02). Node-graph components CMP-146..153, CMP-236..238 (E37). SCR-084..087 (E35).

## Acceptance criteria
```gherkin
Scenario: Each screen's catalogue checklist is initialled
  Given the sign-off checklists for SCR-080, SCR-088 and SCR-089
  Then every box is drawn and initialled by the reviewer
Scenario: The export privacy promise is designed, not assumed
  Given the SCR-089 export frame
  Then the note stating that bundles carry no account ids, keys or armed state is present in the UI itself and an annotation names the test that verifies it
Scenario: Every DS contribution is a catalogue entry (edge)
  Given any visual introduced by these screens
  Then it maps to a CMP id in 15-component-catalogue.md, or a new entry is proposed in the same PR — no one-off visuals
Scenario: Motion respects reduced motion (failure/edge)
  Given prefers-reduced-motion: reduce
  Then every specified transition has a defined non-animated equivalent and no information is conveyed only by movement
```

## Technical notes / design
The IR inspector renders large JSON: specify the >100 KB treatment (syntax highlighting in a worker, per the SCR-088 performance note) and what the UI shows while it is pending.

## Test plan
DS review board sign-off on the contributions; contrast and target-size audit; a walkthrough importing a deliberately invalid bundle to check the failure frames tell the user what to do next.

## Security notes
SCR-089 is the epic's main data-egress surface: the design must make the scope-stripping explicit and must never offer an "export with account bindings" affordance. SCR-088 exposes IR only, never credentials.

## Accessibility notes
SCR-080 table semantics with sortable-column announcements; state as text not colour; conflict banner `role="status"`; SCR-088 `<pre>` region with a described-by note plus the expandable tree alternative; SCR-089 import diff as a table with per-row failure text.

## Performance notes
Annotate the 500-row virtualisation target (≤4 ms scripting per frame) and the ≤2 s validation target for a 100-rule import bundle with per-rule streaming.

## Observability
Annotate `rule.exported`, `rule.imported`, `rule.ir_viewed`, `rule.ir_copied` trigger points.

## Definition of Done
Frames + DS entries merged; motion spec documented; CDO sign-off; catalogue entries updated with the Figma links; Done ≥2 sprints before Sprint 16.

## Dependencies
`blocked_by`: **E36-D01**.

## Branch
`design/rule-list-inspector-hifi`.

## References
`docs/plan/14-screens-catalogue.md` SCR-080, SCR-088, SCR-089 · `docs/plan/15-component-catalogue.md` §5 and §7A · `docs/plan/16-design-system-brief.md`.
""")

add("E36-D04", "Task", "Accessibility design review of the form editor as the mandated non-canvas alternative",
    ["type/design", AREA, "priority/p0", "design", "a11y"], "web", "Sprint 15", "P0 Critical", "Product", "R5 Scope", 2,
    "E36", ["E36-D02", "E36-D03"], """
## Context
`docs/plan/15-component-catalogue.md` CMP-146 designates the form editor the *primary accessible-equivalent mechanism* for the node-graph canvas — "mandated because free-form 2D graph manipulation cannot be made fully keyboard-equivalent to mouse drag-connect at parity speed". That makes an a11y defect in SCR-081 a blocker for E37 as well as for E36. This review happens on the designs, before engineering starts, so problems are cheap.

## Scope / Deliverables
- Keyboard model review for SCR-081: tab order across Scope → Trigger → Conditions → Actions → Options → action bar; the documented hotkeys `Ctrl+S`, `Ctrl+Enter`, `Alt+G`, `Alt+↑/↓` (reorder), `Ctrl+D` (duplicate row) — verify none collides with browser/AT reserved keys and that every one has a non-hotkey equivalent control.
- Screen-reader script: what is announced when a row is added, removed, reordered, when the error count changes (CMP-234 announces on every recompile), when the round-trip indicator changes state, and when a graph-only read-only card is focused.
- Naming review: every condition row a labelled group "Condition N of M"; metric options carry description and unit; `(estimated)` is in the accessible name, not only a colour/icon.
- Verify the plain-language summary is wired as the accessible description of the rule (US-RULE-004 NFR).
- Contrast/target-size/zoom audit of D02 and D03 frames (AA: 4.5:1 text, 3:1 non-text, 24×24 targets, 200 % zoom reflow).
- Review SCR-080 table semantics, SCR-088's tree alternative and SCR-089's import diff table.
- Produce an a11y annotation layer in Figma plus an acceptance list that E36-Q03 audits against 1:1.

## Out of scope
Auditing built software (E36-Q03). The node canvas's own a11y strategy (E37).

## Acceptance criteria
```gherkin
Scenario: The whole rule can be authored without a pointer, on paper
  Given the D02 frames and the annotated keyboard model
  When a keyboard-only walkthrough of "create rule, add condition, group, add action, set scope, save" is performed
  Then every step has a focusable control, a visible focus indicator and an announcement, with no drag-only or hover-only affordance
Scenario: Nothing is colour-only
  Given the four round-trip indicator states and the armed-state tags
  Then each is distinguished by text and shape as well as colour
Scenario: A hotkey collision is caught (failure)
  Given a documented hotkey that conflicts with a screen-reader pass-through or browser shortcut
  Then it is flagged, an alternative is agreed and 14-screens-catalogue.md is updated
Scenario: Reduced motion and 200% zoom (edge)
  Then all frames reflow without horizontal scrolling at 200% and no state is conveyed only by animation
```

## Technical notes / design
Use the WCAG 2.2 AA criteria list in `docs/plan/05-accessibility-standard.md` as the checklist; record each criterion as pass / fail / N-A with the frame reference.

## Test plan
Manual walkthrough with the accessibility specialist plus one assistive-technology user if available; findings logged as comments on the D02/D03 frames and as blocking items where Level A/AA is at stake.

## Security notes
N/A.

## Accessibility notes
This ticket *is* the accessibility artefact; its output is the acceptance list used by E36-Q03 and by the E37 a11y gate.

## Performance notes
Announcement volume is a usability risk: specify that validation announcements are throttled and that the error-count live region is polite, not assertive, except for blocking mismatch.

## Definition of Done
Annotation layer complete; criterion-by-criterion checklist attached; all Level A/AA blockers resolved in D02/D03 before they close; accessibility specialist sign-off comment; acceptance list linked from E36-Q03.

## Dependencies
`blocked_by`: **E36-D02**, **E36-D03**.

## Branch
`design/rule-form-a11y-review`.

## References
`docs/plan/05-accessibility-standard.md` · `docs/plan/14-screens-catalogue.md` SCR-080/081/083/088/089 · `docs/plan/15-component-catalogue.md` CMP-145, CMP-146, CMP-234.
""")

add("E36-D05", "Task", "Assemble and sign off the rule-form-editor engineering handoff pack",
    ["type/design", AREA, "priority/p1", "design", "handoff"], "web", "Sprint 15", "P1 High", "Product", "R5 Scope", 2,
    "E36", ["E36-D04"], """
## Context
Engineering on E36 starts in Sprint 16. The design-ahead rule (`00-planning-brief.md`) requires the designs to be Done and handed over before then. This ticket packages D02/D03/D04 into something a developer can build from without asking a question.

## Scope / Deliverables
- Handoff document listing, per screen (SCR-080, SCR-081, SCR-083, SCR-088, SCR-089): the frame links, every state, the redlines/spacing tokens, the component mapping to CMP ids, and the copy deck (every label, placeholder, validation message, empty state, warning and confirmation string, exactly as it must ship).
- Component contract table aligning each Figma component with its catalogue props: CMP-140 (`metric`, `operator`, `value|metricRef`, `joinToNext`, `invalid`), CMP-141 (`rows`, `mode: and|or|advanced`), CMP-142 (`actionType`, `params`), CMP-143 (`trigger`, `timeframe`), CMP-144 (`symbol`, `accounts`, `appliesTo`), CMP-145 (`rule`, `armMode`), CMP-233, CMP-234 (`diagnostics[{id,severity,message,anchor,fixHint}]`, `onFocusAnchor`), CMP-235 (`mode`, `lossyWarning`, `dirty`), CMP-155, CMP-157 (`category`), CMP-158, CMP-159.
- The a11y acceptance list from D04 and the motion spec from D03, embedded by reference.
- A Storybook story list per component that design will review in D06 (matching the catalogue's Storybook column, e.g. CMP-140: Default, MetricRefValue, JoinAnd, JoinOr, Invalid).
- A live walkthrough session with the implementing engineers and QA, recorded, with open questions answered on the ticket.

## Out of scope
Building anything. Design QA of the built result (E36-D06).

## Acceptance criteria
```gherkin
Scenario: No open questions at handoff
  Given the walkthrough session has happened
  Then every question raised is answered on the ticket or converted into a tracked follow-up, and the implementing engineers confirm in writing that they can build without further design input
Scenario: Copy is complete
  Given the copy deck
  Then every string visible in any state of the five screens appears in it, including the twelve template descriptions and every validation message
Scenario: A component has no catalogue home (edge)
  Given a visual in the frames with no CMP id
  Then handoff is blocked until it is either mapped to an existing component or added to 15-component-catalogue.md
Scenario: Late design change (failure)
  Given a frame changes after handoff
  Then the pack is versioned, the delta is communicated on the consuming engineering tickets, and the change is reflected in 14-screens-catalogue.md
```

## Technical notes / design
The copy deck is the source of truth for i18n keys later; name keys `rules.editor.*`, `rules.list.*`, `rules.templates.*`, `rules.ir.*`, `rules.io.*`.

## Test plan
The pack is "tested" by the engineers restating the build plan back; QA confirms every state in the pack is testable and has an observable outcome.

## Security notes
The copy deck fixes the safety-critical strings (native-SL invariant notice CMP-158, estimated-detector warning, flatten acknowledgement) — these may not be reworded in code without design and security review.

## Accessibility notes
The pack must carry the D04 acceptance list verbatim; it is the checklist E36-Q03 audits against.

## Performance notes
Restate the budgets engineers must build to: ≤300 ms validation round-trip, ≤500 ms p95 compile/round-trip, 500-row list ≤4 ms scripting/frame, ≤300 ms template instantiation.

## Observability
Restate the audit/analytics event list so instrumentation ships with the feature, not after it.

## Definition of Done
Pack published and linked from the epic and from every E36-S* ticket; walkthrough recorded; engineers' written confirmation; CDO sign-off; Status Done before Sprint 16 starts.

## Dependencies
`blocked_by`: **E36-D04**.

## Branch
`design/rule-form-handoff`.

## References
`docs/plan/14-screens-catalogue.md` §6 · `docs/plan/15-component-catalogue.md` §5, §7A · `docs/plan/02-definition-of-ready-done.md` §3.1.
""")

add("E36-D06", "Task", "Design QA the shipped form editor against the handoff pack",
    ["type/design", AREA, "priority/p1", "design", "design-qa"], "web", "Sprint 17", "P1 High", "Product", "R5 Scope", 2,
    "E36", ["E36-S02", "E36-D05"], """
## Context
Design QA closes the loop: the built SCR-080/081/083/088/089 are compared against the D05 handoff pack, state by state, before the epic can be Done (`02-definition-of-ready-done.md` design sign-off).

## Scope / Deliverables
- Side-by-side review of every state of the five screens in the running web app (light/dark, compact/comfortable, 100 %/125 %/200 % zoom).
- Storybook review of CMP-140..145, CMP-155, CMP-157..159, CMP-233..235 against the story list in the handoff pack.
- Copy audit: every shipped string matched to the copy deck; deviations either fixed or accepted with a recorded reason.
- Token audit: no hard-coded colours, spacings or durations; `space.rulegroup.indent` used for group indentation; motion durations from the DS scale with reduced-motion fallbacks verified.
- A prioritised defect list (blocker / major / minor) filed as Bugs against E36, with blockers fixed before epic close.

## Out of scope
Functional/black-box testing (E36-Q05), a11y audit (E36-Q03), performance (E36-Q04).

## Acceptance criteria
```gherkin
Scenario: Every packed state exists in the build
  Given the handoff pack's state inventory
  Then each state is reachable in the running app or in Storybook, and any missing state is filed as a blocker
Scenario: No ad hoc visuals
  Given a token audit of the rules feature styles
  Then no hard-coded colour, spacing or duration values remain outside the design tokens
Scenario: A blocker is found late (failure)
  Given a blocker-severity mismatch discovered in Sprint 17
  Then the epic does not close until it is fixed or an explicit CDO waiver with rationale is recorded on this ticket
Scenario: Dark mode and density parity (edge)
  Given every screen at both densities in dark mode
  Then contrast and layout match the frames, including the amber graph-only and blocking mismatch states
```

## Technical notes / design
Review against a build deployed from `main` at the sprint boundary, not a local branch, so what is signed off is what ships.

## Test plan
Checklist-driven manual pass; screenshots attached per state; defects linked.

## Security notes
Verify the safety-critical strings are present and unmodified: CMP-158 native-SL notice in the editor composition (a presence test also exists in unit tests), the estimated-detector warning, the `flatten_all_positions` acknowledgement, and the SCR-089 export scope-stripping note.

## Accessibility notes
Spot-check focus visibility and announcement behaviour; anything deeper is E36-Q03's remit.

## Performance notes
Note any perceived jank in the condition list at 12+ rows; hand quantitative work to E36-Q04.

## Observability
Confirm the analytics/audit events fire where the pack says they do (verified via the dev event console).

## Definition of Done
Every screen reviewed and initialled; defect list filed and triaged; blockers closed; CDO design sign-off comment recorded on the epic.

## Dependencies
`blocked_by`: **E36-S02** (the editor must exist), **E36-D05** (the pack it is measured against).

## Branch
N/A (review ticket; defects get their own `fix/` branches).

## References
`docs/plan/14-screens-catalogue.md` §6 · `docs/plan/16-design-system-brief.md` · `docs/plan/02-definition-of-ready-done.md`.
""")

json.dump(T, open(os.path.join(os.path.dirname(__file__), "backlog", "_e36_a.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(len(T), sum(t["estimate"] for t in T[1:]))
