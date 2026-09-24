# -*- coding: utf-8 -*-
"""REPRO: a user-supplied action whose name starts with `spawn_` is never called.

`_execute_actions` routes ANY action whose type starts with `spawn_` /
`spawn_blocking_` to `_spawn_actor` BEFORE consulting
`machine.logic.actions`. Built-in creators (`log`, `assign`, ...) do the
opposite -- they are resolved only "when the user has NOT supplied an action of
the same name" (base_interpreter.py ~2846). So `spawn_` is the one prefix that
silently claims a name out of the user's namespace, and the failure surfaces as
a fatal ActorSpawningError naming a "service" the machine never declared.

`MachineLogic(strict=True)` does not warn at build time; nothing warns until
the state is entered at runtime.

Catalogue impact: B2 `spawn_all_legs`, B3 `spawn_entry_order`.
"""
from __future__ import annotations
import asyncio
from xstate_statemachine import (Interpreter, MachineLogic, create_machine,
                                 SimulatedClock, ActorSpawningError)

CFG = {
    "id": "m",
    "actionErrorPolicy": "rollback",
    "onUnhandled": "defer",
    "guardErrorPolicy": "raise",
    "strictTargets": True,
    "strict": True,
    "initial": "a",
    "context": {},
    "states": {"a": {"on": {"GO": {"target": "b", "actions": ["ACTION"]}}},
               "b": {}},
}


async def run(name):
    called = []

    def impl(i, ctx, e, ad):
        called.append(name)

    import copy, json
    c = json.loads(json.dumps(CFG).replace("ACTION", name))
    logic = MachineLogic(actions={name: impl}, strict=True)
    m = create_machine(c, logic=logic)          # builds clean either way
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    await asyncio.sleep(0.03)
    err = None
    try:
        await i.send("GO")
        await asyncio.sleep(0.06)
    except BaseException as e:
        err = e
    st = sorted(i.current_state_ids)
    try:
        await i.stop()
    except BaseException:
        pass
    return dict(name=name, user_action_called=called, ids=st,
                status=i.status, error=repr(err)[:90])


async def main():
    for n in ("place_all_legs", "spawn_all_legs", "spawn_entry_order",
              "spawn_blocking_thing"):
        print(await run(n))


asyncio.run(main())
