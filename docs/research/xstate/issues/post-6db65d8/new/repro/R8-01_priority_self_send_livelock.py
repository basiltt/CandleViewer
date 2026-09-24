"""R8b - MINIMAL: a `send(priority=True)` issued FROM AN ENTRY ACTION is an
UNBOUNDED self-feeding loop. `maxIterations` never trips, `stop()` never
returns, and no hook fires: the machine spins for ever, silently.

#180: "External `send(priority=True)` is never charged ... Accounting is
by *who issued it*: only engine completions and self-raised events count."
The implementation decides "external" by the `engine_completion` kwarg on
`_deliver_priority` (interpreter.py:2342-2375), which is False for EVERY
`send(priority=True)` -- including one issued by the machine's own action,
which is self-generated work by the very definition #180 states. The
non-priority path DOES route an action's own send to the internal queue
and charge it (`_issued_from_own_action()`, interpreter.py:898-908);
`priority=True` bypasses that branch entirely.

Contrast rows in this probe:
  priority_self_send      -> unbounded, stop() hangs         (the defect)
  plain_self_send         -> bounded by maxIterations, trips (the control)

Both service kinds; the async engine only (SyncInterpreter has no
priority lane). Watchdog 8 s -- a timeout IS the observed result.
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
from xstate_statemachine.exceptions import RunawayChainError
LAPS={"n":0}
class Drop(PluginBase):
    def __init__(self): self.reasons={}
    def on_event_dropped(self,i,e,reason=None,**kw):
        self.reasons[str(reason)]=self.reasons.get(str(reason),0)+1
def prio(i,ctx,e,ad):
    LAPS["n"]+=1
    try:
        r=i.send("P",priority=True)
        if asyncio.iscoroutine(r): r.close()
    except Exception: pass
def plain(i,ctx,e,ad):
    LAPS["n"]+=1
    try:
        r=i.send("P")
        if asyncio.iscoroutine(r): r.close()
    except Exception: pass
def cfg(action):
    return {"id":"r8b","initial":"a","context":{"n":0},"maxIterations":25,
     "states":{"a":{"entry":[action],"on":{"P":{"target":"b"}}},
               "b":{"entry":[action],"on":{"P":{"target":"a"}}}}}
def mk(action,kind):
    return create_machine(cfg(action),logic=MachineLogic(
        actions={"prio":prio,"plain":plain},services={"s":make_service(kind)}))
async def one(action,kind,wd=8.0):
    LAPS["n"]=0; d=Drop()
    i=Interpreter(mk(action,kind)).use(d)
    row={"self_send":action,"service_kind":kind,"maxIterations":25,"watchdog_s":wd}
    t0=time.perf_counter()
    try:
        await asyncio.wait_for(i.start(),wd)
        row["start"]="ok"
    except asyncio.TimeoutError:
        row.update({"start":"TIMEOUT","start_seconds":round(time.perf_counter()-t0,2),
                    "laps_at_watchdog":LAPS["n"],"trip_observable":False,
                    "drops":d.reasons,"outcome":"LIVELOCK"})
        return row
    await asyncio.sleep(0.3)
    row["laps"]=LAPS["n"]
    row["trip_observable"]=isinstance(i.last_error,RunawayChainError) or bool(d.reasons)
    row["last_error"]=repr(i.last_error)[:60]; row["drops"]=d.reasons
    t1=time.perf_counter()
    try:
        await asyncio.wait_for(i.stop(),wd); row["stop"]="ok"
    except asyncio.TimeoutError:
        row["stop"]="HUNG"; row["outcome"]="LIVELOCK"
    row["stop_seconds"]=round(time.perf_counter()-t1,2)
    row.setdefault("outcome","bounded")
    return row
async def child(action,kind):
    row=await one(action,kind)
    print("ROW:"+__import__("json").dumps(row,default=str))
async def main():
    import sys,os,json,subprocess
    if len(sys.argv)>2 and sys.argv[1]=="--cell":
        await child(sys.argv[2],sys.argv[3]); return 0
    rows=[]
    for a in ("plain","prio"):
        for k in ("def","async def"):
            env={**os.environ,"PYTHONIOENCODING":"utf-8","PYTHONUTF8":"1"}
            try:
                p=subprocess.run([sys.executable,os.path.abspath(__file__),"--cell",a,k],
                                 capture_output=True,text=True,timeout=20,env=env)
                line=[l for l in p.stdout.splitlines() if l.startswith("ROW:")]
                if line: rows.append(json.loads(line[0][4:]))
                else: rows.append({"self_send":a,"service_kind":k,
                     "outcome":"LIVELOCK","detail":"child produced no row",
                     "trip_observable":False})
            except subprocess.TimeoutExpired:
                rows.append({"self_send":a,"service_kind":k,"outcome":"LIVELOCK",
                  "detail":"child process exceeded a 20s WALL watchdog: the spin "
                           "starves the event loop, so even asyncio.wait_for() "
                           "inside the process never fires",
                  "trip_observable":False})
    bad=[r for r in rows if r.get("outcome")=="LIVELOCK" or not r.get("trip_observable",True)]
    emit("r8b_priority_self_send_livelock",{"rows":rows,"livelocks":bad,
      "source":"interpreter.py:2342-2375 `_deliver_priority(engine_completion=False)` for every send(priority=True), vs :898-908 `_issued_from_own_action()` on the non-priority path",
      "result":"FAIL" if bad else "PASS"})
    return 1 if bad else 0
raise SystemExit(asyncio.run(main()))
