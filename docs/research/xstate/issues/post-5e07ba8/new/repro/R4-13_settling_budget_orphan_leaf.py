# -*- coding: utf-8 -*-
"""R4-13: A runaway-chain trip during transient ("always") settling leaves an
active leaf whose ancestors are INACTIVE. The machine reports "running"
with no error, and a save->restore->save round-trip silently rewrites the
persisted configuration to a different (ancestor-repaired) shape.

Standalone, derived from battle-5e07ba8/fuzz/repros.py::d10.

Root cause: sync_interpreter.py's settling-budget break (~lines 812-824)
has no `last_error` / `last_transition_ok` reporting, unlike the
event-chain budget break a few hundred lines above it (~lines 700-733).

Exits 1 (defect present) while:
  - the live machine has an orphaned active leaf (ancestors not active), and
  - the machine reports last_transition_ok True / last_error None, and
  - a snapshot taken before a restore differs from one taken after.
Exits 0 once the settling-budget trip is reported and/or repairs the
active-node set consistently.
"""
from __future__ import annotations

import json

from xstate_statemachine import SyncInterpreter, create_machine

CFG = {
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

LOGIC_KW = dict(
    guards={"g_true": lambda c, e: True},
    services={"svc_ok": lambda i, c, e: {"ok": 1}},
)


def main() -> int:
    from xstate_statemachine import MachineLogic

    machine = create_machine(CFG, logic=MachineLogic(**LOGIC_KW))
    i = SyncInterpreter(machine)
    i.start()

    active = {n.id for n in i._active_state_nodes}
    orphans = sorted(
        n.id
        for n in i._active_state_nodes
        if n.parent is not None and n.parent not in i._active_state_nodes
    )

    s1 = i.get_persisted_snapshot()
    r = SyncInterpreter.from_snapshot(json.dumps(s1, default=str), machine)
    s2 = r.get_persisted_snapshot()

    print(f"OBSERVED: live active={sorted(active)}")
    print(f"OBSERVED: orphaned leaves (ancestors inactive)={orphans}")
    print(
        f"OBSERVED: status={i.status} last_transition_ok={i.last_transition_ok} "
        f"last_error={i.last_error!r}"
    )
    print(f"OBSERVED: save1 configuration={s1['configuration']}")
    print(f"OBSERVED: save2 (post-restore) configuration={s2['configuration']}")
    print(
        "EXPECTED: no orphan active node; a settling-budget trip surfaces via "
        "last_error/last_transition_ok; save->restore->save is stable "
        "(save1 == save2)"
    )

    defect = bool(orphans) and i.last_transition_ok and i.last_error is None
    configs_differ = s1["configuration"] != s2["configuration"]
    print(f"\nVERDICT: orphan_unreported={defect} configs_differ={configs_differ}")
    return 1 if (defect or configs_differ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
