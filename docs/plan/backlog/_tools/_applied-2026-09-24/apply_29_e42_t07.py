import json

t07 = {
    "key": "E42-T07",
    "kind": "Task",
    "title": "Statechart inspector read API: machines, config, chain_trips, dropped_receipts, deferred depth, Stately export",
    "labels": ["type/feature", "area/accounts-admin", "priority/p1", "security", "statechart"],
    "component": "api",
    "phase": "P4 Admin & Governance",
    "sprint": "Sprint 16",
    "priority": "P1 High",
    "perspective": "Development",
    "risk": "None",
    "estimate": 3,
    "parent": "E42",
    "blocked_by": ["E50-T60", "E50-T01", "E42-T01"],
    "milestone": "R4 Admin GA",
    "body": (
        "## Context\n"
        "Every catalogue lifecycle is built directly on `xstate-statemachine==0.9.1` (ADR-0016 "
        "Accepted). A restored machine with `chain_trips > 0` is admitted degraded and stays "
        "latched until an operator acknowledges it in the admin inspector "
        "(`29-statechart-adoption-plan.md` §4, the `chain_trips` latch note). This task is the read "
        "API that inspector needs: it never queries a live `Interpreter` on the hot path "
        "(MUSTNOT-03) - it reads the `CvAuditPlugin` write-ahead `machine_events` table and the "
        "persisted snapshot, both landed by `E50-T60`.\n\n"
        "## Scope / Deliverables\n"
        "- `GET /admin/statecharts` - list live machines by kind (`machine_key`), current "
        "published state/enum, `machine_hash`, and `chain_trips`/`dropped_receipts`/deferred-depth "
        "counters, sourced from the persisted snapshot and the `CvMetricsPlugin` `cv_machine_*` "
        "gauges (E50-T60), never from a live interpreter call.\n"
        "- `GET /admin/statecharts/{machine_key}` - context summary (redacted per the same rules "
        "as the WS topic in `E17-T08`), full config, and current configuration path.\n"
        "- `GET /admin/statecharts/{machine_key}/export` - the Stately-compatible JSON export for "
        "the chart registered under that `machine_hash` (from `statechart/registry.py`), so the "
        "admin screen can render the same diagram Stately would.\n"
        "- Per-entity RBAC identical in shape to `E17-T08`'s topic authorisation (owner/account "
        "scope), reusing the same permission check rather than a bespoke one.\n\n"
        "## Out of scope\n"
        "- The latch-acknowledge write path and the inspector UI itself - **E42-S08**.\n"
        "- The live-update WS topic - **E17-T08**; this is the point-in-time/list read model.\n\n"
        "## Acceptance criteria\n"
        "```gherkin\n"
        "Scenario: List live machines\n"
        "  Given several B1-B20 machines are running\n"
        "  When I call GET /admin/statecharts\n"
        "  Then I see one row per machine with kind, state, machine_hash, chain_trips and dropped_receipts\n"
        "\n"
        "Scenario: No hot-path interpreter query\n"
        "  Given the read API serves a request\n"
        "  Then it is answered from the persisted snapshot and machine_events, with no call into a "
        "live Interpreter instance\n"
        "\n"
        "Scenario: Stately export matches the registered chart\n"
        "  Given a machine_hash registered in statechart/registry.py\n"
        "  When I call the export endpoint\n"
        "  Then the returned JSON round-trips through the same Stately schema used to author the chart\n"
        "```\n\n"
        "## Technical notes / design\n"
        "This is a pure read model over `CvAuditPlugin`'s write-ahead `machine_events` rows plus "
        "the quiescent snapshot store (`statechart/persistence.py`); it does not import "
        "`xstate_statemachine` directly (`CV-LINT-IMPORT` applies) and does not hold or construct "
        "an `Interpreter`. Built directly on the library via the factory/registry/plugin surface: "
        "no hand-rolled state machine, no enum+transition table, no shim, no dual-runtime.\n\n"
        "## Test plan\n"
        "Contract: response shapes against `22-api-openapi.yaml`. Integration: list/detail/export "
        "for at least one machine of each catalogue kind; RBAC refusal cross-account. Perf: p99 "
        "under the SCR budget for admin reads.\n\n"
        "## Security notes\n"
        "Context summaries are redacted the same way as the `E17-T08` topic payloads; the export "
        "endpoint reveals chart structure only, never live secrets/context values.\n\n"
        "## Performance notes\n"
        "Read-model only; no interpreter construction cost on the request path.\n\n"
        "## Observability\n"
        "Reuses `cv_machine_*` families from `E50-T60`.\n\n"
        "## Definition of Done\n"
        "Per `02-definition-of-ready-done.md` §3.2; `tests/xstate_contract` gate green.\n\n"
        "## Dependencies\n"
        "Blocked by **E50-T60**, **E50-T01** and **E42-T01**.\n\n"
        "## Branch\n"
        "`feat/e42-statechart-inspector-api`\n\n"
        "## References\n"
        "`docs/plan/29-statechart-adoption-plan.md` §4 (chain_trips latch), §4d; "
        "`docs/plan/28-statechart-catalogue.md`.\n"
    ),
}

with open("E42.json", encoding="utf-8") as f:
    e42 = json.load(f)

if not any(t["key"] == "E42-T07" for t in e42):
    e42.append(t07)

with open("E42.json", "w", encoding="utf-8") as f:
    json.dump(e42, f, ensure_ascii=False, indent=2)

print("T07 added")
