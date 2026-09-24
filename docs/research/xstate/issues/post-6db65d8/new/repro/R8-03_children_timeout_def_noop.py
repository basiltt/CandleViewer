"""R6b - MINIMAL: `start(children_timeout=)` (#181) does not bound start()
when the child's slow entry action is a plain `def`.

#181: "a slow child's `async def` entry action no longer holds `await
start()` for its whole duration." The fix is an `asyncio.wait_for` around
the bring-ups (`_await_actor_bringups(timeout=)`), which can only pre-empt
at an `await`. A plain `def` entry action runs ON THE LOOP THREAD inside
`child.start()`, so the timeout cannot fire until the action returns --
and with N children the delay is N x duration, serialized.

ONE child, 3 s entry, children_timeout=0.2. Both spellings.
"""
import asyncio, json, os, sys, time
from xstate_statemachine import (Interpreter, MachineLogic, PluginBase,
                                 SyncInterpreter, create_machine)

KINDS = ("def", "async def")


def emit(name, data):
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    print(txt)


def make_service(kind, delay=0.0, value=None):
    val = {"v": 1} if value is None else value
    if kind == "def":
        def svc(i, ctx, e):
            if delay:
                time.sleep(delay)
            return val
        return svc

    async def asvc(i, ctx, e):
        if delay:
            await asyncio.sleep(delay)
        return val
    return asvc
import logging
class Cap(logging.Handler):
    def __init__(self): super().__init__(level=logging.WARNING); self.msgs=[]
    def emit(self,r): self.msgs.append(r.getMessage())
KID={"id":"kid","initial":"k","context":{},"states":{"k":{"entry":["slow"]}}}
PAR={"id":"r6b","initial":"up","context":{},"states":{
 "up":{"invoke":{"src":"kid","id":"kid"},"on":{"P":{"target":"off"}}},"off":{}}}
D=3.0
async def one(kind,timeout,n):
    if kind=="def":
        def slow(i,c,e,a): time.sleep(D)
    else:
        async def slow(i,c,e,a): await asyncio.sleep(D)
    kid=create_machine(KID,logic=MachineLogic(actions={"slow":slow}))
    par=dict(PAR); par["states"]=dict(PAR["states"])
    par["states"]["up"]=dict(PAR["states"]["up"])
    par["states"]["up"]["invoke"]=[{"src":"kid","id":f"kid{j}"} for j in range(n)]
    m=create_machine(par,logic=MachineLogic(actions={"slow":slow},services={"kid":kid}))
    cap=Cap(); lg=logging.getLogger("xstate_statemachine"); lg.addHandler(cap)
    i=Interpreter(m); t0=time.perf_counter()
    await asyncio.wait_for(i.start(children_timeout=timeout), 300)
    s=round(time.perf_counter()-t0,2)
    await asyncio.wait_for(i.stop(),60); lg.removeHandler(cap)
    return {"entry_kind":kind,"children":n,"child_entry_seconds":D,
            "children_timeout":timeout,"start_seconds":s,
            "bounded":s < timeout+1.0,
            "overrun_factor":round(s/timeout,1),
            "warning_logged":any("#181" in m or "still starting" in m for m in cap.msgs)}
async def main():
    rows=[await one(k,0.2,n) for k in ("async def","def") for n in (1,5)]
    bad=[r for r in rows if not r["bounded"]]
    emit("r6b_children_timeout_def_noop",{"rows":rows,"unbounded":bad,
      "source":"interpreter.py:601 _await_actor_bringups(timeout=) -- wait_for cannot preempt a `def` entry action running on the loop thread",
      "result":"FAIL" if bad else "PASS"})
    return 1 if bad else 0
raise SystemExit(asyncio.run(main()))
