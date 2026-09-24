import json

s08 = {
    "key": "E42-S08",
    "kind": "Story",
    "title": "Build the admin statechart inspector screen: machine list, state diagram, event timeline, latch acknowledge",
    "labels": ["type/feature", "area/accounts-admin", "priority/p1", "security", "qa", "design", "a11y", "statechart"],
    "component": "web",
    "phase": "P4 Admin & Governance",
    "sprint": "Sprint 17",
    "priority": "P1 High",
    "perspective": "Development",
    "risk": "None",
    "estimate": 5,
    "parent": "E42",
    "blocked_by": ["E42-T07", "E42-S01", "E09-S04"],
    "milestone": "R4 Admin GA",
    "body": (
        "## Context\n"
        "Every catalogue lifecycle is built directly on `xstate-statemachine==0.9.1` (ADR-0016 "
        "Accepted). Operators need one screen to see it: which machines are running, what state "
        "each is in, its transition history, and - critically - the place to acknowledge a "
        "`chain_trips`-latched machine so it can rejoin the order path "
        "(`29-statechart-adoption-plan.md` §4, the `chain_trips` latch note).\n\n"
        "## Scope / Deliverables\n"
        "- Machine list view sourced from `E42-T07`'s `GET /admin/statecharts`: kind, current "
        "state, `machine_hash`, `chain_trips`, `dropped_receipts`, deferred depth; degraded rows "
        "(`chain_trips > 0`) visually distinct and filterable.\n"
        "- State diagram rendered from the Stately-compatible JSON export (`E42-T07` export "
        "endpoint), with the current state highlighted.\n"
        "- Event timeline from `machine_events` (the `CvAuditPlugin` write-ahead audit trail, "
        "E50-T60): transitions, guard refusals, dropped-receipt events, in chronological order per "
        "machine.\n"
        "- **Latch-acknowledge action**: an operator control that clears a `chain_trips` latch, "
        "gated by step-up re-auth (`E09-S04`'s elevation, action class `killswitch`-equivalent "
        "severity) and written to the audit trail with actor, machine, and prior `chain_trips` "
        "count.\n\n"
        "## Out of scope\n"
        "- The read API itself and RBAC on it - **E42-T07**.\n"
        "- Any change to how `chain_trips` is incremented or to the degraded-admission behaviour - "
        "that is the B-chart/gateway logic (`statechart/gateway.py`), not this screen.\n\n"
        "## Acceptance criteria\n"
        "```gherkin\n"
        "Scenario: See a degraded machine\n"
        "  Given a machine restored with chain_trips > 0\n"
        "  When I open the inspector\n"
        "  Then it is listed as degraded with its chain_trips and dropped_receipts counts visible\n"
        "\n"
        "Scenario: Acknowledge a latch\n"
        "  Given I am viewing a degraded machine\n"
        "  When I acknowledge it with step-up re-auth\n"
        "  Then the latch clears, the machine resumes serving order-path commands, and the "
        "acknowledgement is audited with my identity\n"
        "\n"
        "Scenario: Acknowledge without elevation is refused\n"
        "  Given I have not completed step-up recently\n"
        "  When I attempt to acknowledge a latch\n"
        "  Then the server refuses it and I am prompted for step-up\n"
        "\n"
        "Scenario: State diagram matches the running chart\n"
        "  Given a machine of a given machine_hash\n"
        "  When I view its diagram\n"
        "  Then it matches the Stately export for that hash and highlights the current state\n"
        "```\n\n"
        "## Technical notes / design\n"
        "The screen consumes `E42-T07`'s read API for the list/detail/export and `E17-T08`'s "
        "`machines.{entity}.state` topic for live updates while the screen is open; it never opens "
        "a bespoke polling loop against the interpreter. The acknowledge action calls a dedicated "
        "admin write route (paired with `E42-T07`) that is itself gated by the E09-S04 step-up "
        "elevation and goes through `statechart/gateway.py` (`cv_re_mint`-style payload-only "
        "wrapper, CV-C68 containment) rather than touching the interpreter directly. Built directly "
        "on the library via the factory/registry/plugin/gateway surface: no hand-rolled state "
        "machine, no enum+transition table, no shim, no dual-runtime.\n\n"
        "## Test plan\n"
        "Unit: degraded-row filter, diagram highlight logic. Contract: acknowledge route against "
        "`22-api-openapi.yaml`, step-up gate enforced. Integration: end-to-end latch-and-acknowledge "
        "against a machine seeded with `chain_trips > 0`. E2E: list -> detail -> diagram -> "
        "timeline -> acknowledge with step-up, refusal without step-up. a11y: axe-core plus a "
        "manual pass on the diagram and timeline (non-visual equivalents for state/edges).\n\n"
        "## Security notes\n"
        "The acknowledge action is a dangerous action per the `E09-S04` permission registry "
        "(`is_dangerous`); it is audited at high severity with actor, machine, and prior "
        "`chain_trips` count, and it never reveals context values not already redacted by the read API.\n\n"
        "## Accessibility notes\n"
        "The state diagram and event timeline provide a non-visual equivalent (a text list of "
        "states/edges and a table for the timeline) so the screen is usable without the rendered "
        "diagram; the acknowledge control has an explicit accessible name naming the machine, not a "
        "generic \"Confirm\".\n\n"
        "## Performance notes\n"
        "Diagram and timeline are read from the E42-T07 API; live updates ride the existing "
        "`E17-T08` topic rather than a per-screen poll.\n\n"
        "## Observability\n"
        "`cv_machine_latch_acknowledged_total`, reusing the `cv_machine_*` families from `E50-T60`.\n\n"
        "## Definition of Done\n"
        "Per `02-definition-of-ready-done.md` §3.2; Security engineer sign-off on the acknowledge "
        "gate; design-qa and QA sign-off absorbed into E42-D05/E42-Q04 per the plan's one-line Scope "
        "additions.\n\n"
        "## Dependencies\n"
        "Blocked by **E42-T07**, **E42-S01** and **E09-S04**.\n\n"
        "## Branch\n"
        "`feat/e42-statechart-inspector-screen`\n\n"
        "## References\n"
        "`docs/plan/29-statechart-adoption-plan.md` §4 (chain_trips latch), §4d; "
        "`docs/plan/28-statechart-catalogue.md`; `docs/plan/14-screens-catalogue.md`.\n"
    ),
}

with open("E42.json", encoding="utf-8") as f:
    e42 = json.load(f)

if not any(t["key"] == "E42-S08" for t in e42):
    e42.append(s08)

with open("E42.json", "w", encoding="utf-8") as f:
    json.dump(e42, f, ensure_ascii=False, indent=2)

print("S08 added")
