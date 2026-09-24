# -*- coding: utf-8 -*-
"""Verify #112 on 3ed3099: a settle-budget (maxIterations) trip during the
transient ("always") settling loop is OBSERVABLE and leaves a legally
repaired configuration (root cause: sync_interpreter.py's settle-budget
break previously reported nothing and could leave an orphaned leaf).

The original R4-13 repro's exact machine now fails at create_machine()
time (a `RootTargetError`/`InvalidConfigError`, since #108 rejects a
transition targeting the machine root at BUILD time) -- that config is a
superseded scenario, not a live repro of the settle-budget trip anymore.
This script instead drives a genuine settle-budget trip with a machine
that is legal to build (mutually-retargeting `always` transitions that
never touch the root), and checks the CHANGELOG's specific claims:

Criteria:
  1. Triggering the settle-budget trip (`maxIterations` exceeded during
     `always` settling) leaves `last_transition_ok is False`.
  2. `last_error` (or `_last_action_error`) is set to a RunawayChainError
     (or similar) when the budget trips -- NOT silently None.
  3. After the trip, every active leaf's full ancestor chain is active
     (no orphaned leaf) -- `_repair_configuration()` ran.
  4. `save() -> restore() -> save()` round-trip is now STABLE: the
     snapshot taken live matches one taken after a from_snapshot() restore
     (both already ancestor-complete, so restore does not silently rewrite
     the shape).
  5. The original R4-13 repro's machine, which relied on `always` ->
     machine root, is now rejected at machine-build time with a typed
     `InvalidConfigError` (superseded by #108) rather than exhibiting the
     torn-configuration defect at runtime.

Exits 0 iff all pass.
"""
from __future__ import annotations

import json

from xstate_statemachine import (
    InvalidConfigError,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

# A machine whose `always` transitions ping-pong between two real (non-root)
# states forever, so the settle budget trips without ever entering the root.
CFG = {
    "id": "m2",
    "initial": "a",
    "maxIterations": 3,
    "states": {
        "a": {"always": {"target": "#m2.b", "guard": "g_true"}},
        "b": {"always": {"target": "#m2.a", "guard": "g_true"}},
    },
}

LOGIC_KW = dict(guards={"g_true": lambda c, e: True})


def check_settle_trip_observable() -> bool:
    machine = create_machine(CFG, logic=MachineLogic(**LOGIC_KW))
    i = SyncInterpreter(machine)
    i.start()

    ok_flag = i.last_transition_ok is False
    err = getattr(i, "last_error", None) or getattr(i, "_last_action_error", None)
    ok_error_set = err is not None
    print(f"[trip_observable] last_transition_ok={i.last_transition_ok!r} last_error={err!r}")

    orphans = sorted(
        n.id
        for n in i._active_state_nodes
        if n.parent is not None and n.parent not in i._active_state_nodes
    )
    ok_no_orphans = orphans == []
    print(f"[configuration_repaired] orphans={orphans}")

    s1 = i.get_snapshot()
    restored = SyncInterpreter.from_snapshot(s1, machine, verify_machine_hash=False)
    s2 = restored.get_snapshot()
    d1, d2 = json.loads(s1), json.loads(s2)
    d1.pop("version", None)
    d2.pop("version", None)
    ok_roundtrip_stable = sorted(d1.get("configuration", [])) == sorted(
        d2.get("configuration", [])
    )
    print(
        f"[roundtrip_stable] before={sorted(d1.get('configuration', []))} "
        f"after={sorted(d2.get('configuration', []))}"
    )

    return ok_flag and ok_error_set and ok_no_orphans and ok_roundtrip_stable


def check_original_repro_superseded() -> bool:
    """The original R4-13 CFG (always -> #m, the root) must now be
    rejected at build time with a typed InvalidConfigError."""
    cfg = {
        "id": "m",
        "initial": "b",
        "maxIterations": 1,
        "always": {"target": "#m.b", "guard": "g_true"},
        "states": {
            "b": {
                "type": "parallel",
                "states": {
                    "a": {
                        "initial": "a",
                        "always": {"target": "#m", "guard": "g_true"},
                        "states": {"a": {}},
                    },
                    "b": {
                        "initial": "a",
                        "invoke": {
                            "id": "v",
                            "src": "svc_ok",
                            "onDone": "#m.b",
                            "onError": "#m.b",
                        },
                        "states": {"a": {}},
                    },
                },
            }
        },
    }
    try:
        create_machine(
            cfg,
            logic=MachineLogic(
                guards={"g_true": lambda c, e: True},
                services={"svc_ok": lambda i, c, e: {"ok": 1}},
            ),
        )
        print("[original_repro_superseded] FAIL: machine built without error")
        return False
    except InvalidConfigError as exc:
        print(f"[original_repro_superseded] OK: rejected at build time: {exc}")
        return True


def main() -> int:
    results = [
        check_settle_trip_observable(),
        check_original_repro_superseded(),
    ]
    n_ok = sum(results)
    print(f"\n{n_ok}/{len(results)} criteria passed")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
