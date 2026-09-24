from xstate_statemachine import SyncInterpreter, MachineLogic, create_machine
CFG={"id":"m","initial":"a","onUnhandled":"defer","states":{"a":{"on":{"GO":"b"}},"b":{"on":{"BACK":"a"}}}}
s=SyncInterpreter(create_machine(CFG,logic=MachineLogic())); s.start()
false_pos=0; n=3000
for k in range(n):
    r=s.send("GO",wait=True) if hasattr(s.send,'__call__') else None
    if r is not None and r.deferred and r.changed: false_pos+=1
    r2=s.send("BACK",wait=True)
    if r2 is not None and r2.deferred and r2.changed: false_pos+=1
print("false deferred=True with changed=True:",false_pos,"of",2*n)
print("deferred_count",s.deferred_count)
ids=getattr(s,"_deferred_this_step",None)
print("_deferred_this_step size:",len(ids) if ids is not None else "n/a")
