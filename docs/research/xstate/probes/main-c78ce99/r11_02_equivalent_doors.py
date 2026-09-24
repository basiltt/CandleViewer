import asyncio, json, sys
from xstate_statemachine import create_machine, Interpreter, SyncInterpreter

CFG={"id":"m","initial":"a","context":{},"states":{
 "a":{"on":{"WAKE":{"target":"b"}},"after":{60000:{"target":"late"}}},
 "b":{},"late":{}}}

def snap(iv):
    s=iv.get_persisted_snapshot()
    return json.loads(s) if isinstance(s,str) else json.loads(json.dumps(s))

def run_sync(mut,label):
    m=create_machine(dict(CFG, strict=True))
    iv=SyncInterpreter(m).start()
    s=snap(iv); iv.stop()
    mut(s)
    iv2=SyncInterpreter.from_snapshot(json.dumps(s),m)
    iv2.start()
    import time; t=time.time()
    while time.time()-t<1.0:
        iv2._pump() if hasattr(iv2,'_pump') else None
        time.sleep(0.05)
        if iv2.current_state_ids!={"m.a"}: break
    print(label, sorted(iv2.current_state_ids), "err=",iv2.last_error if hasattr(iv2,'last_error') else None)
    iv2.stop()

# 1) baseline: forge configuration directly (no event needed)
def mut_cfg(s):
    s["status"]="running"; 
    for k in ("configuration","state_ids","states"):
        if k in s: s[k]=["m.late"]
run_sync(mut_cfg,"1 forged-configuration:")

# 2) v2 pending_events with an 'after' record (upcast engine-minted per #214)
def mut_v2(s):
    s["version"]=2
    s["pending_events"]=[{"type":"after.60000.m.a","kind":"after"}]
    s.pop("scheduled_sends",None)
run_sync(mut_v2,"2 v2-pending-after:")

# 3) scheduled_sends forged after record (the reported door)
def mut_ss(s):
    s["scheduled_sends"]=[{"type":"after.60000.m.a","kind":"after","engine":True,"remaining_ms":1.0}]
run_sync(mut_ss,"3 scheduled_sends-after:")

# 4) v3 pending_events forged with engine:true
def mut_v3(s):
    s["pending_events"]=[{"type":"after.60000.m.a","kind":"after","engine":True}]
run_sync(mut_v3,"4 v3-pending-engine-true:")
