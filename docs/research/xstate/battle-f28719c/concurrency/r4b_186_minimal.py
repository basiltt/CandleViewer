"""R4b - MINIMAL: #186 ("a `configuration` that contradicts `state_ids` is
corrupt") is NOT enforced. `base_interpreter.py:1722` still reads

    restore_ids = snapshot.get("configuration") or snapshot["state_ids"]

so the two fields are never COMPARED. What refuses most tampering is the
older #143 legality check at :1749, which only asks whether the chosen
list has one leaf per region. Whenever BOTH lists are individually legal
but name DIFFERENT states, `configuration` silently wins and `state_ids`
is ignored -- the "silently win or silently lose" case #186 names.

Both engines, both service kinds.
"""
import asyncio, copy, json
from common2 import (Interpreter, MachineLogic, SyncInterpreter,
                     create_machine, emit, make_service)
CFG={"id":"r4b","initial":"a","context":{"n":0},"states":{
 "a":{"on":{"S":{"target":"b"}}},"b":{"on":{"S":{"target":"a"}}}}}
def mk(kind): return create_machine(CFG,
    logic=MachineLogic(services={"s":make_service(kind)}))
async def base(kind):
    i=Interpreter(mk(kind)); await i.start(); await i.send("S",wait=True)
    b=i.get_persisted_snapshot(); await i.stop()
    return b if isinstance(b,dict) else json.loads(b)
def restore(engine,kind,b):
    cls=Interpreter if engine=="async" else SyncInterpreter
    try:
        r=cls.from_snapshot(json.dumps(b),mk(kind))
        return {"disposition":"ACCEPTED","status":r.status,
                "restored_to":sorted(getattr(r,'current_state_ids',[]))}
    except Exception as e: return {"disposition":f"refused:{type(e).__name__}"}
async def main():
    rows=[]
    for kind in ("def","async def"):
        b0=await base(kind)          # truthfully in "r4b.b"
        assert b0["state_ids"]==["r4b.b"], b0["state_ids"]
        for engine in ("async","sync"):
            # Both lists individually LEGAL, but they name different states.
            b=copy.deepcopy(b0); b["configuration"]=["r4b.a"]   # lies
            r=restore(engine,kind,b)
            rows.append({"case":"configuration lies, state_ids truthful",
                         "engine":engine,"kind":kind,
                         "snapshot_state_ids":b["state_ids"],
                         "snapshot_configuration":b["configuration"],
                         "truth":"r4b.b",**r})
            # Mirror: state_ids lies, configuration truthful.
            b=copy.deepcopy(b0); b["state_ids"]=["r4b.a"]
            r=restore(engine,kind,b)
            rows.append({"case":"state_ids lies, configuration truthful",
                         "engine":engine,"kind":kind,
                         "snapshot_state_ids":b["state_ids"],
                         "snapshot_configuration":b["configuration"],
                         "truth":"r4b.b",**r})
    bad=[r for r in rows if r["disposition"]=="ACCEPTED"]
    emit("r4b_186_minimal",{"rows":rows,
        "accepted_contradictions":len(bad),
        "expected":"every row refused with SnapshotCorruptError (#186)",
        "result":"FAIL" if bad else "PASS"})
    return 1 if bad else 0
raise SystemExit(asyncio.run(main()))
