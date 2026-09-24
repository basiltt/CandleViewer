# -*- coding: utf-8 -*-
"""R9-05: snapshots are unauthenticated -- documentation/affordance repro.

Two independent demonstrations, both standalone (stdlib + xstate_statemachine
only), inlined from the round-9 evidence scripts (r2_readside_matrix.py /
r3_version_downgrade.py) so this file needs no other artefact:

1. A *consistent* forgery of `configuration` + `state_ids` together relocates
   the restored machine to a leaf the honest snapshot never visited.
2. A `version` downgrade (absent, or 0 + hash removed/None) bypasses the
   drift check (`check_identity`, persistence.py) and restores into a
   structurally DIFFERENT machine.

Both are DOCUMENTED as intended (check_identity's own docstring says a v0
payload is unchecked by design). This script exits 1 to mark "still present
as designed" -- i.e. it is a design-constraint confirmation, not evidence of
a code regression. Exit 0 would mean the library started refusing both
forgeries outright (a stricter default than currently documented).
"""
from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import Interpreter, create_machine
from xstate_statemachine.clock import SimulatedClock

A_SPEC = {
    "id": "m",
    "initial": "a",
    "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"BACK": "a"}}},
}
B_SPEC = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {"on": {"GO": "b", "JUMP": "c"}},
        "b": {"on": {"BACK": "a"}},
        "c": {"on": {"BACK": "a"}},
    },
}


async def take_snapshot() -> dict:
    i = Interpreter(create_machine(A_SPEC), clock=SimulatedClock())
    await i.start()
    await asyncio.sleep(0.01)
    blob = i.get_persisted_snapshot()
    await i.stop()
    return blob


async def main() -> int:
    blob = await take_snapshot()
    bad = []

    # --- 1. consistent configuration/state_ids forgery relocates -------
    forged = json.loads(json.dumps(blob))
    forged["state_ids"] = ["m.b"]
    forged["configuration"] = ["m", "m.b"]
    try:
        r = Interpreter.from_snapshot(json.dumps(forged), create_machine(A_SPEC))
        leaves = sorted(n.id for n in r._active_state_nodes if not n.states)
        print("1. consistent forgery -> ACCEPTED, leaves =", leaves)
        if leaves == ["m.b"]:
            bad.append("consistent-forgery-relocated")
    except Exception as exc:  # noqa: BLE001
        print("1. consistent forgery -> REFUSED", type(exc).__name__)

    # --- 2. version downgrade bypasses drift check ----------------------
    mB = create_machine(B_SPEC)
    for label, mutate in (
        ("version absent + hash removed", lambda b: (b.pop("version", None), b.pop("machine_hash", None))),
        ("version=0 + hash removed", lambda b: (b.__setitem__("version", 0), b.pop("machine_hash", None))),
        ("version=0 + hash=None", lambda b: b.update(version=0, machine_hash=None)),
    ):
        b = json.loads(json.dumps(blob))
        mutate(b)
        try:
            r = Interpreter.from_snapshot(json.dumps(b), mB)
            await r.start()
            await r.send("JUMP")  # event A never declared
            await asyncio.sleep(0.02)
            print(f"2. {label} -> ACCEPTED into DRIFTED machine, after JUMP =",
                  sorted(r.current_state_ids))
            bad.append(f"version-downgrade:{label}")
            await r.stop()
        except Exception as exc:  # noqa: BLE001
            print(f"2. {label} -> REFUSED {type(exc).__name__}")

    print("\nVERDICT:", "DOCUMENTED BEHAVIOUR STILL PRESENT" if bad else "both forgeries now refused")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
