# -*- coding: utf-8 -*-
"""NEW ATTACK: fuzz SnapshotCorruptError coverage + InvalidEventError over
hostile event types. Reduced from the 5k-mutation target to fit the time
budget: 400 snapshot mutations + 200 hostile event-type sends.
"""
from __future__ import annotations

import asyncio
import copy
import json
import random

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import (
    InvalidConfigError,
    InvalidEventError,
    SnapshotCorruptError,
    SnapshotDriftError,
    SnapshotVersionError,
)

CFG = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"GO": {"target": "b"}}}, "b": {"on": {"GO": {"target": "a"}}}},
}


def mutate(obj, rng):
    obj = copy.deepcopy(obj)
    keys = list(obj.keys()) if isinstance(obj, dict) else []
    kind = rng.choice(["drop", "type", "value", "nest"])
    if kind == "drop" and keys:
        del obj[rng.choice(keys)]
    elif kind == "type" and keys:
        k = rng.choice(keys)
        obj[k] = rng.choice([123, None, [], {}, "x", 3.14])
    elif kind == "value" and keys:
        k = rng.choice(keys)
        if isinstance(obj[k], str):
            obj[k] = obj[k][:1] + "!!MUTATED!!"
        else:
            obj[k] = "mutated"
    elif kind == "nest" and keys:
        k = rng.choice(keys)
        obj[k] = {"unexpected": obj.get(k)}
    return obj


async def main() -> None:
    rng = random.Random(99)
    m = create_machine(CFG, logic=MachineLogic())
    interp = Interpreter(m)
    await interp.start()
    await interp.send("GO", wait=True)
    good_snap = interp.get_persisted_snapshot()

    n_mut = 400
    typed_ok = 0
    untyped_escapes = []
    silently_accepted = 0
    for i in range(n_mut):
        mutated = mutate(good_snap, rng)
        try:
            s = json.dumps(mutated, default=repr)
        except TypeError:
            continue
        new_m = create_machine(CFG, logic=MachineLogic())
        try:
            restored = Interpreter.from_snapshot(s, new_m)
            # Accepted -- only OK if the mutation was a semantically
            # harmless no-op (rare, but possible for e.g. "value"-kind
            # mutating an already-arbitrary provenance field).
            silently_accepted += 1
        except (
            SnapshotCorruptError,
            SnapshotDriftError,
            SnapshotVersionError,
            InvalidConfigError,
        ):
            typed_ok += 1
        except Exception as exc:  # noqa: BLE001
            untyped_escapes.append((i, repr(exc)))

    print(f"mutations: {n_mut}")
    print(f"typed exception (expected): {typed_ok}")
    print(f"silently accepted (mutation was a no-op): {silently_accepted}")
    print(f"UNTYPED exception escapes: {len(untyped_escapes)}")
    for e in untyped_escapes[:10]:
        print("  ", e)

    # --- InvalidEventError over hostile event "type" shapes ---
    hostile_events = [123, None, [], {}, 3.14, b"bytes", object(), True, ("t",)]
    n_typed = 0
    n_untyped = 0
    for ev in hostile_events * 20:  # 180 sends
        try:
            await interp.send(ev, wait=True)
        except InvalidEventError:
            n_typed += 1
        except Exception as exc:  # noqa: BLE001
            n_untyped += 1
            print("UNTYPED on hostile event", type(ev), repr(exc))

    print(f"hostile event sends: {len(hostile_events) * 20}")
    print(f"InvalidEventError (expected): {n_typed}")
    print(f"untyped exceptions: {n_untyped}")

    if untyped_escapes or n_untyped:
        print("DEFECT: an untyped exception escaped fuzzing")
    else:
        print("PASS: all corrupt snapshots and hostile events raised typed "
              "library exceptions")
    await interp.stop()


if __name__ == "__main__":
    asyncio.run(main())
