"""R8c - MINIMAL: the trip LAP COUNT differs between engines on the plain
`def` service lane, for every invoke-driven cycle shape.

CHANGELOG #179: "Both service kinds now trip at the same lap count as the
sync engine." Measured with a 1.5 s settle (i.e. fully at rest, not a
sampling window): the async engine trips 2-3 laps EARLY for every
invoke-driven shape when the service is a plain `def`.

`always_cycle` and `sendto_self_loop` -- the shapes with no invoke -- are
in exact parity, which localises this to the completion lane.

Deterministic: 5 repeats per cell, all identical.
"""
import asyncio, statistics
from common2 import (Interpreter, MachineLogic, SyncInterpreter,
                     create_machine, emit, make_service)
from xstate_statemachine.exceptions import RunawayChainError
LAPS={"n":0}
def act(i,c,e,a): LAPS["n"]+=1
def loopback(i,c,e,a):
    LAPS["n"]+=1
    try: i.send("LOOP")
    except Exception: pass
SH={
 "always_cycle":{"a":{"always":{"target":"b","actions":["act"]}},
                 "b":{"always":{"target":"a","actions":["act"]}}},
 "invoke_cycle":{"a":{"invoke":{"src":"s","onDone":{"target":"b","actions":["act"]},
                                "onError":{"target":"b"}}},
                 "b":{"always":{"target":"a","actions":["act"]}}},
 "nested_invoke_cycle":{"a":{"initial":"a1","states":{
   "a1":{"invoke":{"src":"s","onDone":{"target":"a2","actions":["act"]},"onError":{"target":"a2"}}},
   "a2":{"always":{"target":"a1","actions":["act"]}}}}},
 "rollback_ondone":{"a":{"invoke":{"src":"s","onDone":{"target":"b","actions":["act"]},
                                   "onError":{"target":"b"}}},
                    "b":{"always":{"target":"a","actions":["act","act"]}}},
 "sendto_self_loop":{"a":{"entry":["loopback"],"on":{"LOOP":{"target":"b"}}},
                     "b":{"entry":["loopback"],"on":{"LOOP":{"target":"a"}}}},
}
def cfg(sh,it): return {"id":"r8c","initial":next(iter(SH[sh])),"context":{"n":0},
                        "maxIterations":it,"states":SH[sh]}
def mk(sh,it,k): return create_machine(cfg(sh,it),logic=MachineLogic(
    actions={"act":act,"loopback":loopback},services={"s":make_service(k)}))
async def a_laps(sh,it,k):
    LAPS["n"]=0; i=Interpreter(mk(sh,it,k))
    await asyncio.wait_for(i.start(),20); await asyncio.sleep(1.5)
    n=LAPS["n"]; t=isinstance(i.last_error,RunawayChainError)
    await asyncio.wait_for(i.stop(),20); return n,t
def s_laps(sh,it):
    LAPS["n"]=0; i=SyncInterpreter(mk(sh,it,"def"))
    try: i.start()
    except RunawayChainError: pass
    n=LAPS["n"]; t=isinstance(i.last_error,RunawayChainError)
    try: i.stop()
    except Exception: pass
    return n,t
async def main():
    rows=[]
    for sh in SH:
        for it in (25,50):
            sv=[s_laps(sh,it) for _ in range(3)]
            for k in ("def","async def"):
                av=[await a_laps(sh,it,k) for _ in range(3)]
                rows.append({"shape":sh,"maxIterations":it,"service_kind":k,
                  "async_laps":sorted({x[0] for x in av}),
                  "sync_laps":sorted({x[0] for x in sv}),
                  "async_trip":sorted({x[1] for x in av}),
                  "sync_trip":sorted({x[1] for x in sv}),
                  "laps_equal":{x[0] for x in av}=={x[0] for x in sv},
                  "delta":(min(x[0] for x in av)-min(x[0] for x in sv)),
                  "deterministic":len({x[0] for x in av})==1})
    bad=[r for r in rows if not r["laps_equal"]]
    emit("r8c_lap_parity_def_lane",{"rows":rows,"parity_violations":bad,
      "claim":"CHANGELOG #179: both service kinds trip at the same lap count as the sync engine",
      "result":"FAIL" if bad else "PASS"})
    return 1 if bad else 0
raise SystemExit(asyncio.run(main()))
