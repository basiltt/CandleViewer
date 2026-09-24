# -*- coding: utf-8 -*-
"""Sync-engine parity for the denied-conflation claim, plus an isolated
minimal machine (no catalogue) to rule out rig/catalogue artefacts."""
import json
from xstate_statemachine import create_machine, SyncInterpreter

CFG = {"id":"m","initial":"a","context":{},
       "guardErrorPolicy":"raise","onUnhandled":"ignore",
       "states":{"a":{"on":{"E":[{"target":"b","guard":"g"}]}},"b":{}}}

class H:
    def __init__(self): self.seen=[]
    def on_unhandled_event(self,i,e,a,d): self.seen.append(d)
    def __getattr__(self,n): return lambda *a,**k: None

def run(mode):
    def g(ctx,ev):
        if mode=="raise": raise RuntimeError("boom")
        return False
    from xstate_statemachine import MachineLogic
    m=create_machine(CFG, logic=MachineLogic(guards={"g":g}))
    h=H(); it=SyncInterpreter(m); it._plugins.append(h); it.start()
    err=None
    try: r=it.send("E", wait=True)
    except Exception as e: err=type(e).__name__; r=None
    return {"mode":mode,"disposition":h.seen,
            "denied":(r.denied if r is not None and hasattr(r,'denied') else None),
            "changed":(r.changed if r is not None and hasattr(r,'changed') else None),
            "raised":err}

out=[run("false"),run("raise")]
print(json.dumps(out,indent=1))
json.dump(out,open("repro/f5b_sync_parity.json","w"),indent=1)
