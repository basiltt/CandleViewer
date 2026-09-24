# -*- coding: utf-8 -*-
"""D5-persistence-2 minimal repro: #113's non-`str` event-type guard is
enforced on `send()` but NOT on the restore path.

#113 made a non-`str` event `type` raise `InvalidEventError` (also a
`TypeError`) instead of escaping the type hierarchy. `n6_hostile_and_hooks.py`
confirms that holds for the LIVE `send()` path: 8/9 hostile types are refused.

`from_snapshot()` reconstructs pending events via `events.restore_event()`,
which reads `record["type"]` and hands it to the event constructor with no
type check -- `persistence.check_shape()` only asserts that the key is
PRESENT (`'pending_events' must be a list of event records with a 'type'`),
never that it is a string. So a blob is the one way to get a non-`str` event
type into a live interpreter.

This is the persistence-relevant half of #113 and it is the half that
matters for an OMS: a snapshot comes back from Redis/disk/a queue, i.e. from
outside the process, whereas `send()` is called by our own code.

Below: five non-`str` types, each accepted, each producing a live event
whose `.type` is not a string, and each silently matching nothing -- so the
event is swallowed by `onUnhandled` instead of being refused at the door.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.events import restore_event
from xstate_statemachine.plugins import PluginBase

CONFIG = {
    "id": "rp",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"GO": {"target": "b", "actions": ["bump"]}}},
               "b": {}},
}


def bump(i, ctx, e, ad): ctx["n"] += 1      # noqa: ANN001,E704


def build():
    return create_machine(CONFIG, logic=MachineLogic(actions={"bump": bump}))


class Spy(PluginBase):
    def __init__(self) -> None:
        self.seen: list[tuple[str, object]] = []

    def on_event_dropped(self, i, e, reason):        # noqa: ANN001
        self.seen.append(("dropped", getattr(e, "type", "?")))

    def on_unhandled_event(self, i, e, ids, disp):   # noqa: ANN001
        self.seen.append(("unhandled", repr(getattr(e, "type", "?"))))


async def main() -> None:
    i = Interpreter(build(), clock=SimulatedClock())
    await i.start(); await asyncio.sleep(0.02)
    blob = i.get_snapshot()
    await i.stop()

    print("unit level: restore_event() on a non-str `type`")
    for bad in (42, None, ["GO"], {"x": 1}, True):
        ev = restore_event({"kind": "event", "type": bad, "payload": {}})
        print(f"   record type={bad!r:<12} -> {type(ev).__name__}"
              f"(type={ev.type!r}, isinstance(str)="
              f"{isinstance(ev.type, str)})")

    print("\nend-to-end: the blob is ACCEPTED and the machine runs")
    for bad in (42, None, ["GO"], {"x": 1}, True):
        d = json.loads(blob)
        d["pending_events"] = [{"kind": "event", "type": bad, "payload": {}}]
        spy = Spy()
        try:
            j = Interpreter.from_snapshot(json.dumps(d), build(),
                                          clock=SimulatedClock())
        except Exception as exc:  # noqa: BLE001
            print(f"   type={bad!r:<12} REFUSED {type(exc).__name__}")
            continue
        j.use(spy)
        await j.start(); await asyncio.sleep(0.04)
        print(f"   type={bad!r:<12} ACCEPTED status={j.status} "
              f"states={sorted(j.current_state_ids)} n={j.context['n']} "
              f"hooks={spy.seen}")
        if j.status == "running":
            await j.stop()

    print("\n   -> a non-`str` event type reaches a live interpreter only via"
          "\n      a restore. #113 guards send(); check_shape() asserts the"
          "\n      'type' key exists but never that it is a string.")


if __name__ == "__main__":
    asyncio.run(main())
