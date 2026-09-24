# -*- coding: utf-8 -*-
"""Isolate the #167 delta: entry-action raise vs transition-action raise.

Library test `TestAsyncRollbackRearmCycleBounded` (tests/test_round6_findings.py)
pins the bounded case with the raising action as the target state's **entry**.
Every B1-B5 contract that hits this shape raises in the `onDone` **transition
actions** list instead. Same rollback, same re-armed invoke.
"""
from __future__ import annotations
import asyncio, json, time

from xstate_statemachine import (Interpreter, MachineLogic, OverflowPolicy,
                                 create_machine)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

ENTRY = {  # library's pinned shape
    "id": "spin", "actionErrorPolicy": "rollback", "initial": "starting",
    "context": {},
    "states": {
        "starting": {"invoke": {"id": "s", "src": "svc",
                                "onDone": {"target": "#spin.recording"}}},
        "recording": {"entry": ["boom"]},
    },
}

TRANS = {  # the contracts' shape
    "id": "spin", "actionErrorPolicy": "rollback", "initial": "starting",
    "context": {},
    "states": {
        "starting": {"invoke": {"id": "s", "src": "svc",
                                "onDone": {"target": "#spin.recording",
                                           "actions": ["boom"]}}},
        "recording": {},
    },
}


class Drops(PluginBase):
    def __init__(self):
        self.dropped = []
    def on_event_dropped(self, i, e, reason):
        self.dropped.append(reason)


async def probe(cfg, label, hold=0.6, hold2=0.9):
    calls = [0]

    def boom(*a):
        raise RuntimeError("boom")

    def svc(i, c, e):
        calls[0] += 1
        return 1

    m = create_machine(json.loads(json.dumps(cfg)),
                       logic=MachineLogic(actions={"boom": boom},
                                          services={"svc": svc}))
    d = Drops()
    i = Interpreter(m).use(d)
    await i.start()
    await asyncio.sleep(hold)
    first = calls[0]
    await asyncio.sleep(hold2)
    later = calls[0]
    out = {"shape": label, "svc_at_%.1fs" % hold: first,
           "svc_at_%.1fs" % (hold + hold2): later,
           "stopped_spinning": first == later,
           "status": i.status,
           "last_error": repr(getattr(i, "last_error", "<absent>")),
           "chain_budget_dropped": "chain_budget" in d.dropped,
           "drop_reasons": sorted(set(d.dropped))}
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        out["stop"] = repr(e)
    return out


async def main():
    res = [await probe(ENTRY, "entry-action (library pinned #167)"),
           await probe(TRANS, "onDone transition-action (B1-B5 contracts)")]
    for r in res:
        print(json.dumps(r), flush=True)
    json.dump(res, open("out_167_delta.json", "w"), indent=1, default=str)
    print("\nDELTA: entry bounded=%s  transition bounded=%s"
          % (res[0]["stopped_spinning"], res[1]["stopped_spinning"]))


asyncio.run(main())
