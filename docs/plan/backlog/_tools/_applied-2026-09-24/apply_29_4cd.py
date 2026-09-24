import json, io, sys

BANNER_S03 = ("> **Re-scoped 2026-09-24 for full xstate-statemachine adoption (ADR-0016 Accepted):** "
    "Session lifetime is B16 `session` built directly on `xstate-statemachine==0.9.1` via the "
    "factory (`statechart/factory.py`); idle-lock and absolute-expiry are coarse `after:` timers "
    "in `machines/B16.session.machine.json` (BENCH-6 p99 55-92 ms is acceptable here, C-04 hoists "
    "revocation onto the root so it fires from every substate). No hand-rolled state machine, no "
    "enum+transition table, no shim, no dual-runtime: `services/api/candleviewer/statechart/bindings/b16_session.py` "
    "is the only place idle/absolute/revocation logic lives.\n\n")

BANNER_S04 = ("> **Re-scoped 2026-09-24 for full xstate-statemachine adoption (ADR-0016 Accepted):** "
    "Step-up re-auth is the step-up sub-state of B16 `session`, built directly on "
    "`xstate-statemachine==0.9.1` via the factory. The per-action-class grace window and the "
    "no-grace list (`live_enablement`, `killswitch`) are guards in "
    "`machines/B16.session.machine.json`; the three-failure downgrade is a transition to a "
    "read-only child state. No hand-rolled state machine, no enum+transition table, no shim, no "
    "dual-runtime.\n\n")

with open("E09.json", encoding="utf-8") as f:
    e09 = json.load(f)

for t in e09:
    if t["key"] == "E09-S03":
        t["estimate"] = 3
        if "statechart" not in t["labels"]:
            t["labels"].append("statechart")
        t["body"] = t["body"].replace("## Context\n", "## Context\n" + BANNER_S03, 1)
        t["body"] = t["body"].replace(
            "## Scope / Deliverables\n",
            "## Scope / Deliverables\n"
            "- Built directly on `xstate-statemachine==0.9.1`: `machines/B16.session.machine.json` "
            "(states `active` / `idle_locked` / `expired`; `after:` timers for the idle deadline and "
            "the 12h absolute lifetime; `REVOKE` arm on the root per C-04) plus "
            "`bindings/b16_session.py` (guards: `is_within_absolute_lifetime`; actions: "
            "`disarm_one_click`, `clear_ws_resubscribe_flag`; no services needed for the timer path).\n",
            1,
        )
        t["body"] = t["body"].replace(
            "## Technical notes / design\n",
            "## Technical notes / design\n"
            "Session lifecycle state (`active`, `idle_locked`, `expired`) is published by "
            "`statechart/factory.build(\"B16\", ...)`/`restore(...)`; the interpreter is the single "
            "source of truth read by the auth decision point (E09-T03) and by the WS gateway "
            "(`E17-T08`). `machine_hash` for B16 is locked in `machines/machine_hashes.lock`. "
            "Snapshot recipe: quiescent HMAC-enveloped blob on every `sessions` row write, restored "
            "on process start via `statechart.restore(\"B16\", blob, clock=..., lane=\"platform\")`. "
            "`CV-LINT-IMPORT` keeps every import of `xstate_statemachine` out of this module; only "
            "`factory.py`/`persistence.py` import it.\n\n",
            1,
        )
        t["body"] = t["body"].replace(
            "## Test plan\n",
            "## Test plan\n"
            "Contract: `tests/xstate_contract/test_b16.py` asserts all B16 states/events, snapshot "
            "round-trip at every quiescence point, and the mandatory-config block (`strict_config`, "
            "`strictTargets`, `actionErrorPolicy`, `guardErrorPolicy`, `onUnhandled`) per "
            "`79-r14-final-readiness-verdict.md` §7. ",
            1,
        )
        t["body"] = t["body"].replace(
            "## Definition of Done\n",
            "## Definition of Done\n"
            "B16 contract test green in the blocking gate (`E50-T31`); `CV-LINT-IMPORT` and "
            "`CV-LINT-HOTPATH` clean. ",
            1,
        )
    elif t["key"] == "E09-S04":
        t["estimate"] = 2
        if "statechart" not in t["labels"]:
            t["labels"].append("statechart")
        t["body"] = t["body"].replace("## Context\n", "## Context\n" + BANNER_S04, 1)
        t["body"] = t["body"].replace(
            "## Scope / Deliverables\n",
            "## Scope / Deliverables\n"
            "- Built directly on `xstate-statemachine==0.9.1`: the step-up sub-state lives inside "
            "`machines/B16.session.machine.json` (states `elevated.{action_class}` / "
            "`readonly_downgrade`); `bindings/b16_session.py` supplies the guard "
            "`grace_window_valid(action_class)` (false unconditionally for `live_enablement` and "
            "`killswitch`, per the no-grace list) and the action `record_step_up_failure` driving "
            "the 3-strike transition to `readonly_downgrade`.\n",
            1,
        )
        t["body"] = t["body"].replace(
            "## Technical notes / design\n",
            "## Technical notes / design\n"
            "Elevation state is the B16 interpreter's own state, not a token claim or a bolted-on "
            "counter: it is revocable and cannot be replayed on another session because each "
            "session owns exactly one B16 machine instance keyed by `session_id`. `machine_hash` "
            "for B16 covers this sub-state too (one chart, one hash). Per-tick verification of the "
            "TOTP code itself stays plain code (not a statechart concern, BENCH-2).\n\n",
            1,
        )
        t["body"] = t["body"].replace(
            "## Test plan\n",
            "## Test plan\n"
            "Contract: `tests/xstate_contract/test_b16.py` (shared with E09-S03) covers the "
            "elevation sub-states, the no-grace guard for `live_enablement`/`killswitch`, and the "
            "3-failure downgrade transition. ",
            1,
        )
        t["body"] = t["body"].replace(
            "## Definition of Done\n",
            "## Definition of Done\n"
            "B16 contract test green in the blocking gate (`E50-T31`). ",
            1,
        )

with open("E09.json", "w", encoding="utf-8") as f:
    json.dump(e09, f, ensure_ascii=False, indent=2)

print("E09 done")
