# Re-repro: snapshot write-side legality + read-side legality + typed errors
import json, asyncio, sys
from xstate_statemachine import create_machine, MachineLogic, Interpreter, SyncInterpreter
from xstate_statemachine.exceptions import XStateMachineError
R={}

# --- A: parallel tear on write side (J-1 / D5-persistence-1)
par={"id":"par","type":"parallel","states":{
 "A":{"initial":"a1","states":{"a1":{"on":{"GO":"a2"}},"a2":{}}},
 "B":{"initial":"b1","states":{"b1":{}}}}}
async def a():
    m=create_machine(par, logic=MachineLogic(actions={"slow":lambda i,c,e,ad=None:None}))
    # snapshot from inside an entry action of A.a2 -> step in flight, leaf present
    got={}
    def ent(i,c,e,ad=None):
        try: got["snap"]=i.get_persisted_snapshot(); got["refused"]=False
        except Exception as ex: got["refused"]=type(ex).__name__
    cfg=json.loads(json.dumps(par)); cfg["states"]["A"]["states"]["a2"]["entry"]=["ent"]
    m=create_machine(cfg, logic=MachineLogic(actions={"ent":ent}))
    i=await Interpreter(m).start(); await i.send("GO", wait=True)
    R["A_refused"]=got.get("refused"); R["A_state_ids"]=got.get("snap",{}).get("state_ids")
    R["A_config"]=got.get("snap",{}).get("configuration")
    await i.stop()
asyncio.run(a())

# --- B: read side, truncated configuration (D5-concurrency-1 / D5-semantics-3)
fz={"id":"fz","initial":"b","states":{"b":{"on":{"GO":"c"}},"c":{}}}
m2=create_machine(fz, logic=MachineLogic())
i2=SyncInterpreter(m2).start()
snap=i2.get_persisted_snapshot()
R["B_good_config"]=snap["configuration"]; R["B_good_ids"]=snap["state_ids"]
snap["configuration"]=[x for x in snap["configuration"] if x=="fz"]
try:
    r=SyncInterpreter.from_snapshot(json.dumps(snap), create_machine(fz, logic=MachineLogic())).start()
    R["B_accepted"]=True; R["B_ids"]=sorted(r.current_state_ids); R["B_status"]=r.status
    r.send("GO"); R["B_ids_after_GO"]=sorted(r.current_state_ids)
except Exception as ex: R["B_accepted"]=False; R["B_err"]=type(ex).__name__

# --- C: typed-error coverage on from_snapshot (merged untyped cluster)
base=i2.get_persisted_snapshot()
muts={"status_list":("status",[]),"status_dict":("status",{}),"history_float":("history",3.14),
 "history_str":("history","junk"),"actors_int":("actors",7),"system_int":("system",7),
 "deferred_null":("deferred",None),"version_str":("version","x"),"version_none":("version",None),
 "version_dict":("version",{}),"output_ok":("output",7)}
res={}
for name,(k,v) in muts.items():
    s=json.loads(json.dumps(base, default=repr)); s[k]=v
    try:
        SyncInterpreter.from_snapshot(json.dumps(s, default=repr), create_machine(fz, logic=MachineLogic()))
        res[name]="ACCEPTED"
    except XStateMachineError as ex: res[name]="TYPED:"+type(ex).__name__
    except Exception as ex: res[name]="UNTYPED:"+type(ex).__name__
R["C_mutations"]=res
R["C_untyped_count"]=sum(1 for v in res.values() if v.startswith("UNTYPED"))

# --- D: non-str event type via restore path (D5-persistence-2)
s=json.loads(json.dumps(base, default=repr)); s["pending_events"]=[{"type":42}]
try:
    r=SyncInterpreter.from_snapshot(json.dumps(s), create_machine(fz, logic=MachineLogic()))
    R["D_restore_nonstr_accepted"]=True
except XStateMachineError as ex: R["D_restore_nonstr_accepted"]="TYPED:"+type(ex).__name__
except Exception as ex: R["D_restore_nonstr_accepted"]="UNTYPED:"+type(ex).__name__
try:
    SyncInterpreter(create_machine(fz, logic=MachineLogic())).start().send(42)
    R["D_send_nonstr"]="ACCEPTED"
except Exception as ex: R["D_send_nonstr"]=type(ex).__name__

# --- E: pre-parse payloads (J-10)
for nm,payload in [("none",None),("badjson","{not json")]:
    try:
        SyncInterpreter.from_snapshot(payload, create_machine(fz, logic=MachineLogic()))
        R["E_"+nm]="ACCEPTED"
    except XStateMachineError as ex: R["E_"+nm]="TYPED:"+type(ex).__name__
    except Exception as ex: R["E_"+nm]="UNTYPED:"+type(ex).__name__
print(json.dumps(R,indent=1,default=str))
