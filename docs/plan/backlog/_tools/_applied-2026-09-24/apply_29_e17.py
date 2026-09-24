import json

new_ticket = {
    "key": "E17-T08",
    "kind": "Task",
    "title": "Statechart-backed WS topic: machines.{entity}.state (state/enum, snapshot+delta, per-entity RBAC)",
    "labels": ["type/feature", "area/backend-platform", "priority/p1", "perf", "security", "statechart"],
    "component": "api",
    "phase": "P1 Core Charting",
    "sprint": "Sprint 06",
    "priority": "P1 High",
    "perspective": "Development",
    "risk": "None",
    "estimate": 3,
    "parent": "E17",
    "blocked_by": ["E17-S02", "E17-S03", "E50-T60"],
    "milestone": "R1 Charting alpha",
    "body": (
        "## Context\n"
        "Every catalogue lifecycle B1-B20 (`28-statechart-catalogue.md`) is built directly on "
        "`xstate-statemachine==0.9.1` from its first line of code (ADR-0016 Accepted, "
        "`29-statechart-adoption-plan.md` §4d). The UI needs to see machine state without ever "
        "querying the interpreter on the hot path (MUSTNOT-03): `machines.{entity}.state` is a "
        "dedicated WS topic, built on the E17 subscription/topic-registry and snapshot+delta "
        "machinery already implemented by E17-S02/E17-S03, fed by the `CvMetricsPlugin`/`CvAuditPlugin` "
        "on_transition hooks landed in E50-T60 rather than by polling any `Interpreter` instance.\n\n"
        "## Scope / Deliverables\n"
        "- Register `machines.{entity}.state` in the E17-S02 topic registry: `entity` is the "
        "catalogue machine's public id (e.g. `order:{order_id}`, `session:{session_id}`, "
        "`kill_switch`, `risk_lockout:{account_id}`).\n"
        "- On every interpreter transition, `CvMetricsPlugin`'s `on_transition` hook (E50-T60) "
        "publishes `{state: <published enum>, context_summary: <redacted>, machine_hash}` onto the "
        "topic; the WS server never calls into `statechart/factory.py` or holds an `Interpreter` "
        "reference to answer a client query.\n"
        "- Snapshot: on subscribe, the current published state is served as an E17-S03 snapshot "
        "frame; subsequent transitions are E17-S03 delta frames on the same sequence numbering as "
        "every other topic (no bespoke resync path for statechart topics).\n"
        "- Per-entity RBAC: subscription is authorised per the E17-S02 topic-registry rule set "
        "against the entity owner/account scope (a manager cannot subscribe to another account's "
        "`risk_lockout` topic).\n"
        "- Coalescing/backpressure/throttling for this topic reuse E17-T03 unchanged; a burst of "
        "rapid transitions (e.g. a chain of `after:` timers) is coalesced to the latest state, "
        "never buffered unboundedly.\n\n"
        "## Out of scope\n"
        "- The admin statechart inspector screen and its read API - **E42-T07**/**E42-S08**; this "
        "task is the live-update topic only, not the historical/list view.\n"
        "- Building or hashing any individual `machine.json` - **E50-S01**/**E50-S02**.\n\n"
        "## Acceptance criteria\n"
        "```gherkin\n"
        "Scenario: Subscribe to a machine's live state\n"
        "  Given I hold a valid subscription to machines.order:o123.state\n"
        "  When the order's B1 machine transitions\n"
        "  Then I receive a delta frame with the new published state within one coalescing window\n"
        "\n"
        "Scenario: No interpreter query on the hot path\n"
        "  Given the WS server publishes a state update\n"
        "  Then it is sourced entirely from the on_transition hook payload, with no call into "
        "factory.py, persistence.py or any Interpreter instance\n"
        "\n"
        "Scenario: RBAC blocks cross-account subscription\n"
        "  Given I am a manager on account A\n"
        "  When I attempt to subscribe to machines.risk_lockout:B.state for account B\n"
        "  Then the subscription is refused\n"
        "```\n\n"
        "## Technical notes / design\n"
        "This topic is a thin publisher over the existing E17 transport; it holds no statechart "
        "import (`CV-LINT-IMPORT` applies transitively - this module is outside the whitelisted "
        "pair). The `machine_hash` is included on every frame so a client can detect it is running "
        "against a stale contract build. Built directly on the library via the factory/plugin "
        "surface: no hand-rolled state machine, no enum+transition table, no shim, no dual-runtime.\n\n"
        "## Test plan\n"
        "Contract: subscribe/snapshot/delta frame shapes against `23-ws-protocol.md` plus the "
        "`machine_hash` field. Integration: transition burst -> coalesced delta, cross-account RBAC "
        "refusal, resubscribe mid-chain of `after:` timers. Perf: no added interpreter query "
        "latency on the hot path (`CV-LINT-HOTPATH` fixture asserts no import site here).\n\n"
        "## Security notes\n"
        "Per-entity RBAC is enforced at subscribe time and re-checked on every RBAC-relevant change "
        "(role change revokes the topic subscription immediately, per the E09-S03 revocation bus).\n\n"
        "## Performance notes\n"
        "Reuses E17-T03 coalescing/backpressure; adds no new per-message allocation beyond the "
        "existing frame envelope.\n\n"
        "## Observability\n"
        "`cv_machine_ws_publish_total{entity_kind}`, reusing the `cv_machine_*` families from "
        "E50-T60's `CvMetricsPlugin`.\n\n"
        "## Definition of Done\n"
        "Per `02-definition-of-ready-done.md` §3.2; `tests/xstate_contract` gate green for every "
        "entity kind exercised; no hot-path interpreter import.\n\n"
        "## Dependencies\n"
        "Blocked by **E17-S02**, **E17-S03** and **E50-T60**.\n\n"
        "## Branch\n"
        "`feat/e17-machine-state-topic`\n\n"
        "## References\n"
        "`docs/plan/23-ws-protocol.md`; `docs/plan/28-statechart-catalogue.md`; "
        "`docs/plan/29-statechart-adoption-plan.md` §4d; `docs/research/xstate/79-r14-final-readiness-verdict.md` §7.\n"
    ),
}

with open("E17.json", encoding="utf-8") as f:
    e17 = json.load(f)

if not any(t["key"] == "E17-T08" for t in e17):
    e17.append(new_ticket)

epic = [t for t in e17 if t["key"] == "E17"][0]
before = epic["estimate"]
children = [t for t in e17 if t.get("parent") == "E17"]
epic["estimate"] = sum(t["estimate"] for t in children)
print("E17 before", before, "after", epic["estimate"])

with open("E17.json", "w", encoding="utf-8") as f:
    json.dump(e17, f, ensure_ascii=False, indent=2)
