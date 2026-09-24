# -*- coding: utf-8 -*-
"""P2 (#222) -- chain-trip latch: exactly-once semantics, and what a
snapshot carries.  STANDALONE.

A: trip once -> chain_trips==1, last_chain_error latched, survives N
   benign events (the #222 claim), clear_chain_error() clears the latch
   but NOT the count; a second trip re-latches and increments.
B: on_chain_budget_exceeded fires exactly once per trip (settle trips
   included) and is ordered before the next on_transition.
C: PERSISTENCE -- does a snapshot taken after a trip carry the fact?
   restore -> chain_trips / last_chain_error on the new interpreter.
D: both engines.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from xstate_statemachine import (Interpreter, MachineLogic, PluginBase,
                                 SyncInterpreter, create_machine)

KIND = os.environ.get("XS_SVC", "async")

CFG = {
    "id": "ct", "initial": "idle", "context": {"n": 0},
    "maxIterations": 5,
    "states": {
        "idle": {"on": {"GO": "spin", "PING": {"actions": ["bump"]}}},
        "spin": {"entry": [{"type": "raise", "params": {"event": "LOOP"}}],
                 "on": {"LOOP": {"target": "spin", "reenter": True},
                        "PING": {"actions": ["bump"]},
                        "RESET": "idle"}},
    },
}


class Rec(PluginBase):
    def __init__(self):
        self.trips = []
        self.events = []

    def on_chain_budget_exceeded(self, interpreter, error, event):
        self.trips.append((type(error).__name__,
                           getattr(event, "type", None)))

    def on_transition(self, interpreter, from_s, to_s, event):
        self.events.append(getattr(event, "type", None))


def build():
    def bump(i, c, e, a):
        c["n"] += 1

    return create_machine(json.loads(json.dumps(CFG)),
                          logic=MachineLogic(actions={"bump": bump}))


async def run_async():
    rec = Rec()
    i = Interpreter(build())
    i.use(rec)
    await i.start()
    out = {}
    await i.send("GO")
    await asyncio.sleep(0.05)
    out["trips_after_1"] = i.chain_trips
    out["latch_after_1"] = type(i.last_chain_error).__name__ \
        if i.last_chain_error else None
    out["last_error_after_1"] = type(i.last_error).__name__ \
        if i.last_error else None
    for _ in range(5):
        await i.send("PING")
    await asyncio.sleep(0.03)
    out["latch_after_5_benign"] = type(i.last_chain_error).__name__ \
        if i.last_chain_error else None
    out["last_error_after_5_benign"] = type(i.last_error).__name__ \
        if i.last_error else None
    out["hook_trips"] = list(rec.trips)
    # C: snapshot the tripped interpreter
    blob = i.get_persisted_snapshot()
    if not isinstance(blob, str):
        blob = json.dumps(blob)
    out["snapshot_has_chain_key"] = [
        k for k in json.loads(blob) if "chain" in k.lower()]
    j = Interpreter.from_snapshot(blob, build())
    out["restored_chain_trips"] = j.chain_trips
    out["restored_latch"] = type(j.last_chain_error).__name__ \
        if j.last_chain_error else None
    # clear + re-trip
    i.clear_chain_error()
    out["latch_after_clear"] = i.last_chain_error
    out["trips_after_clear"] = i.chain_trips
    await i.send("RESET")
    await asyncio.sleep(0.02)
    await i.send("GO")
    await asyncio.sleep(0.05)
    out["trips_after_2"] = i.chain_trips
    out["latch_after_2"] = type(i.last_chain_error).__name__ \
        if i.last_chain_error else None
    out["hook_trips_final"] = len(rec.trips)
    await i.stop()
    return out


def run_sync():
    rec = Rec()
    i = SyncInterpreter(build())
    i.use(rec)
    i.start()
    out = {}
    i.send("GO")
    out["trips_after_1"] = i.chain_trips
    out["latch_after_1"] = type(i.last_chain_error).__name__ \
        if i.last_chain_error else None
    for _ in range(5):
        i.send("PING")
    out["latch_after_5_benign"] = type(i.last_chain_error).__name__ \
        if i.last_chain_error else None
    out["last_error_after_5_benign"] = type(i.last_error).__name__ \
        if i.last_error else None
    blob = i.get_persisted_snapshot()
    if not isinstance(blob, str):
        blob = json.dumps(blob)
    j = SyncInterpreter.from_snapshot(blob, build())
    out["restored_chain_trips"] = j.chain_trips
    out["restored_latch"] = type(j.last_chain_error).__name__ \
        if j.last_chain_error else None
    i.clear_chain_error()
    out["latch_after_clear"] = i.last_chain_error
    i.send("RESET")
    i.send("GO")
    out["trips_after_2"] = i.chain_trips
    out["hook_trips_final"] = len(rec.trips)
    i.stop()
    return out


async def main():
    a = await run_async()
    s = run_sync()
    ok = (a["trips_after_1"] == 1 and a["latch_after_1"]
          and a["latch_after_5_benign"] == a["latch_after_1"]
          and a["latch_after_clear"] is None and a["trips_after_2"] == 2
          and a["hook_trips_final"] == 2
          and s["trips_after_1"] == 1 and s["latch_after_5_benign"]
          and s["trips_after_2"] == 2)
    print(json.dumps({"kind": KIND, "async": a, "sync": s,
                      "VERDICT": "PASS" if ok else "FAIL"}, indent=1,
                     default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
