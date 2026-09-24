# -*- coding: utf-8 -*-
"""R4-12: a transition targeting the machine ROOT empties the configuration.

`{"id": "m", "initial": "a", "states": {"a": {"always": "#m"}}}` builds without
complaint, and starting it leaves the interpreter with NO active states while
`status` is still "running". The same happens for an ordinary `on` transition
targeting the root. The machine accepts events forever and does nothing --
a silent inert machine from a one-character config typo.

`validation.py::_is_dead_always_loop` only rejects `target is t.source`, so a
root-targeting `always` passes build-time validation.

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

ALWAYS_CFG = {"id": "m", "initial": "a", "states": {"a": {"always": "#m"}}}
EVENT_CFG = {
    "id": "m2",
    "initial": "a",
    "states": {"a": {"on": {"GO": "#m2"}}, "b": {}},
}


async def main() -> int:
    failures = []

    # --- async engine, `always` -> root -------------------------------------
    i = Interpreter(create_machine(ALWAYS_CFG, logic=MachineLogic()))
    await i.start()
    ids = sorted(i.current_state_ids)
    snap = i.get_persisted_snapshot()
    d = snap if isinstance(snap, dict) else json.loads(snap)
    print("OBSERVED: async always->#m  state_ids=%r status=%r" % (ids, i.status))
    print("OBSERVED:   snapshot state_ids=%r configuration=%r"
          % (d.get("state_ids"), d.get("configuration")))
    if not ids:
        failures.append("async always->root emptied the configuration")
    await i.stop()

    # --- sync engine, `always` -> root -------------------------------------
    s = SyncInterpreter(create_machine(ALWAYS_CFG, logic=MachineLogic()))
    s.start()
    sids = sorted(s.current_state_ids)
    print("OBSERVED: sync  always->#m  state_ids=%r status=%r" % (sids, s.status))
    if not sids:
        failures.append("sync always->root emptied the configuration")

    # --- sync engine, ordinary `on` -> root --------------------------------
    s2 = SyncInterpreter(create_machine(EVENT_CFG, logic=MachineLogic()))
    s2.start()
    before = sorted(s2.current_state_ids)
    s2.send("GO")
    after = sorted(s2.current_state_ids)
    print("OBSERVED: sync  on GO -> #m2  %r -> %r status=%r"
          % (before, after, s2.status))
    if before and not after:
        failures.append("sync on->root emptied the configuration")

    print("EXPECTED: a transition whose target is the machine root is "
          "rejected at build time (InvalidConfigError), or re-enters the root "
          "and lands on the initial state -- never an empty configuration "
          "with status='running'.")
    print("RESULT:", "PASS" if not failures else "FAIL: " + "; ".join(failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
