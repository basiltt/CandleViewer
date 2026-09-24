"""R4c - MINIMAL: the "silently LOSE" half of #186 is not enforced.

CHANGELOG #186: "`configuration or state_ids` let an emptied or rewritten
`configuration` silently win or silently lose; the two must agree or the
blob is refused with `SnapshotCorruptError`."

`base_interpreter.py:1722` is still `snapshot.get("configuration") or
snapshot["state_ids"]` -- the fields are never compared. The refusals that
DO happen come from the older #143 legality check at :1747-1756, which
only asks whether the winning list has one leaf per region. So:

  * an EMPTIED or REWRITTEN `state_ids` is accepted whenever
    `configuration` is (on its own) legal -- `state_ids` silently loses;
  * a DROPPED `configuration` is accepted (documented v0 fallback).

An operator/auditor who reads `state_ids` out of the blob (the field
`get_persisted_snapshot()` documents at :1448) and the machine that the
same blob restores into then disagree, with no error anywhere.
"""
import asyncio, copy, json
from common2 import (Interpreter, MachineLogic, SyncInterpreter,
                     create_machine, emit, make_service)
CFG={"id":"r4c","initial":"top","context":{"n":0},"states":{"top":{
 "type":"parallel","states":{
  "A":{"initial":"a1","states":{"a1":{"on":{"S":{"target":"a2"}}},"a2":{}}},
  "B":{"initial":"b1","states":{"b1":{"on":{"S":{"target":"b2"}}},"b2":{}}}}}}}
def mk(k): return create_machine(CFG,logic=MachineLogic(services={"s":make_service(k)}))
async def base(k):
    i=Interpreter(mk(k)); await i.start(); await i.send("S",wait=True)
    b=i.get_persisted_snapshot(); await i.stop()
    return b if isinstance(b,dict) else json.loads(b)
def restore(engine,k,b):
    cls=Interpreter if engine=="async" else SyncInterpreter
    try:
        r=cls.from_snapshot(json.dumps(b),mk(k))
        return {"disposition":"ACCEPTED","restored_to":sorted(getattr(r,'current_state_ids',[]))}
    except Exception as e: return {"disposition":f"refused:{type(e).__name__}"}
CASES={
 "state_ids emptied (configuration wins)":     lambda b: b.update({"state_ids":[]}),
 "state_ids rewritten to a different leaf":    lambda b: b.update({"state_ids":["r4c.top.A.a1","r4c.top.B.b1"]}),
 "state_ids rewritten to garbage":             lambda b: b.update({"state_ids":["r4c.NOT_A_STATE"]}),
 "configuration dropped (state_ids wins)":     lambda b: b.pop("configuration",None),
}
async def main():
    rows=[]
    for k in ("def","async def"):
        b0=await base(k)
        for name,fn in CASES.items():
            for engine in ("async","sync"):
                b=copy.deepcopy(b0); fn(b)
                r=restore(engine,k,b)
                rows.append({"case":name,"engine":engine,"kind":k,
                    "blob_state_ids":b.get("state_ids"),
                    "blob_configuration":b.get("configuration"),
                    "truth":sorted(b0["state_ids"]),**r})
    bad=[r for r in rows if r["disposition"]=="ACCEPTED"
         and sorted(r.get("restored_to") or [])!=r["truth"]
         and sorted(r["blob_state_ids"] or [])!=r["truth"]]
    contradiction_accepted=[r for r in rows if r["disposition"]=="ACCEPTED"]
    emit("r4c_186_state_ids_silently_loses",
      {"rows":rows,"accepted_contradictions":len(contradiction_accepted),
       "accepted_and_reader_would_be_misled":bad,
       "source":"base_interpreter.py:1722 `configuration or state_ids` (fields never compared)",
       "result":"FAIL" if contradiction_accepted else "PASS"})
    return 1 if contradiction_accepted else 0
raise SystemExit(asyncio.run(main()))
