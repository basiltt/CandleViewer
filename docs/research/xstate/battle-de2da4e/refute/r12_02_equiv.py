# -*- coding: utf-8 -*-
"""R12-02 refutation: is v2 `engine` minting an ESCALATION over a v3 blob?

Attacker controls the whole snapshot. Compare reachable outcomes:
  A  v2 forged `after` record  -> engine-minted, drives after-transition.
  B  v3 blob, NO forged record, attacker just writes configuration/context
     verbatim to the post-transition state (documented: applied verbatim).
  C  v3 blob + forged after record (control: inert).
If A and B reach the same observable state, minting adds no privilege.
Also: does minimum_version=3 (documented mitigation) close A? Both engines.
"""
from __future__ import annotations
import asyncio, json, os, sys

from xstate_statemachine import Interpreter, SyncInterpreter, create_machine, MachineLogic
from xstate_statemachine.clock import SimulatedClock

SPEC = {
    "id": "vict", "strict": True, "onUnhandled": "error",
    "initial": "waiting", "context": {"fired": 0},
    "states": {
        "waiting": {"after": {600000: {"target": "expired", "actions": ["mark"]}}},
        "expired": {"type": "final"},
    },
}

def mk():
    return create_machine(json.loads(json.dumps(SPEC)),
                          logic=MachineLogic(actions={"mark": lambda i, c, e, a: c.__setitem__("fired", c["fired"] + 1)}))

def blob(m, version, recs, cfg, ctx):
    return json.dumps({
        "machine_hash": m.structure_hash, "version": version, "status": "running",
        "state_ids": list(cfg), "configuration": list(cfg), "context": ctx,
        "pending_events": recs, "deferred": [], "history": {}, "actors": {}, "system": {},
    })

AFTER_REC = [{"kind": "after", "type": "after.600000.vict.waiting", "payload": {}}]

async def run_async(s, **kw):
    m = mk()
    it = Interpreter.from_snapshot(s, m, clock=SimulatedClock(), **kw)
    await it.start()
    for _ in range(200):
        await asyncio.sleep(0)
        if it.status == "done" or it.context.get("fired"):
            break
    out = (it.context.get("fired"), sorted(x.id for x in it.current_state_ids and [] or []) or sorted(it.current_state_ids), it.status)
    await it.stop()
    return out

def run_sync(s, **kw):
    m = mk()
    it = SyncInterpreter.from_snapshot(s, m, **kw)
    it.start()
    out = (it.context.get("fired"), sorted(it.current_state_ids), it.status)
    it.stop()
    return out

def go(label, s, **kw):
    for name, fn in (("async", run_async), ("sync", run_sync)):
        try:
            r = asyncio.run(fn(s, **kw)) if name == "async" else fn(s, **kw)
            print(f"   {label:34s} [{name}] fired={r[0]} states={r[1]} status={r[2]}")
        except Exception as e:
            print(f"   {label:34s} [{name}] REFUSED {type(e).__name__}: {str(e)[:70]}")

if __name__ == "__main__":
    m0 = mk()
    print("R12-02 equivalence probe, cwd=", os.getcwd())
    go("A v2 forged after-record", blob(m0, 2, AFTER_REC, ["vict.waiting"], {"fired": 0}))
    go("B v3 verbatim state write", blob(m0, 3, [], ["vict.expired"], {"fired": 1}))
    go("C v3 forged after (control)", blob(m0, 3, AFTER_REC, ["vict.waiting"], {"fired": 0}))
    go("A' v2 forged + min_version=3", blob(m0, 2, AFTER_REC, ["vict.waiting"], {"fired": 0}), minimum_version=3)
    go("B' v3 verbatim + min_version=3", blob(m0, 3, [], ["vict.expired"], {"fired": 1}), minimum_version=3)
