import json, asyncio
from xstate_statemachine import create_machine, MachineLogic, Interpreter, SyncInterpreter
R={}
def boom(i,c,e,ad=None): raise RuntimeError("boom")
def gboom(c,e): raise RuntimeError("guardboom")

async def main():
    # LIB-01 onUnhandled:error receipt (async, wait=True)
    m=create_machine({"id":"u","initial":"a","onUnhandled":"error","states":{"a":{"on":{"GO":"b"}},"b":{}}},logic=MachineLogic())
    i=await Interpreter(m).start()
    r=await i.send("NOPE", wait=True)
    R["LIB01"]={"changed":r.changed,"error":repr(r.error),"deferred":getattr(r,"deferred",None),
                "status":i.status,"interp_error":repr(i.error)[:60],"last_error":repr(getattr(i,"last_error",None))}
    # C-03b guard-denied under onUnhandled:error
    m3=create_machine({"id":"g","initial":"a","onUnhandled":"error","states":{"a":{"on":{"GO":{"target":"b","guard":"no"}}},"b":{}}},logic=MachineLogic(guards={"no":lambda c,e:False}))
    i3=await Interpreter(m3).start(); r=await i3.send("GO", wait=True)
    R["C03b"]={"changed":r.changed,"error":repr(r.error),"deferred":getattr(r,"deferred",None),
               "status":i3.status,"ids":sorted(i3.current_state_ids)}
    # D-observability-2 guard raise -> receipt
    m4=create_machine({"id":"gr","initial":"a","guardErrorPolicy":"raise","states":{"a":{"on":{"GO":{"target":"b","guard":"bad"}}},"b":{}}},logic=MachineLogic(guards={"bad":gboom}))
    i4=await Interpreter(m4).start(); r=await i4.send("GO", wait=True)
    R["guard_raise"]={"changed":r.changed,"error":repr(r.error)[:60],"status":i4.status,
                      "interp_error":repr(i4.error)[:40],"last_ok":getattr(i4,"last_transition_ok",None)}
    # L-01 actionErrorPolicy fail receipt (async)
    seen=[]
    m5=create_machine({"id":"f","initial":"a","actionErrorPolicy":"fail","states":{"a":{"on":{"GO":"b"}},"b":{"entry":["ok1","boom"]},"c":{}}},
                      logic=MachineLogic(actions={"ok1":lambda i,c,e,ad=None:seen.append("ok1"),"boom":boom}))
    i5=await Interpreter(m5).start(); r=await i5.send("GO", wait=True)
    R["L01"]={"changed":r.changed,"error":repr(r.error)[:50],"ids":sorted(i5.current_state_ids),
              "status":i5.status,"ran":seen}
    try: s=i5.get_persisted_snapshot(); R["L01"]["snapshot"]={"status":s["status"],"state_ids":s["state_ids"]}
    except Exception as ex: R["L01"]["snapshot"]="REFUSED:"+type(ex).__name__
asyncio.run(main())

# J-5 settle budget: sync send_events takes a LIST
N=40
st={"idle":{"on":{"A":"u0","B":"v0"}}}
for p in ("u","v"):
    for k in range(N-1): st[f"{p}{k}"]={"always":f"{p}{k+1}"}
    st[f"{p}{N-1}"]={}
cfg={"id":"ch","initial":"idle","maxIterations":50,"states":st}
i=SyncInterpreter(create_machine(cfg,logic=MachineLogic())).start()
i.send("A"); R["J5_single"]=sorted(i.current_state_ids)
i2=SyncInterpreter(create_machine(cfg,logic=MachineLogic())).start()
i2.send_events(["A","B"])
R["J5_batch"]={"ids":sorted(i2.current_state_ids),"ok":getattr(i2,"last_transition_ok",None),
               "err":repr(getattr(i2,"last_error",None))[:50]}
print(json.dumps(R,indent=1,default=str))
