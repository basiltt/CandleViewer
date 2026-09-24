import json, time, asyncio, threading, logging
from xstate_statemachine import create_machine, MachineLogic, Interpreter, SyncInterpreter
R={}
def boom(i,c,e,ad=None): raise RuntimeError("boom")
def gboom(c,e): raise RuntimeError("guardboom")

# L-01 actionErrorPolicy fail: where does config land + can we snapshot?
cfg={"id":"f","initial":"a","actionErrorPolicy":"fail","states":{
  "a":{"on":{"GO":"b"}},"b":{"entry":["ok1","boom"],"on":{"NEXT":"c"}},"c":{}}}
seen=[]
lg=MachineLogic(actions={"ok1":lambda i,c,e,ad=None:seen.append("ok1"),"boom":boom})
i=SyncInterpreter(create_machine(cfg,logic=lg)).start()
r=i.send("GO")
R["L01_ids_after"]=sorted(i.current_state_ids); R["L01_status"]=i.status
R["L01_receipt"]=(getattr(r,"changed",None),repr(getattr(r,"error",None))[:60])
R["L01_actions_ran"]=seen
r2=i.send("NEXT"); R["L01_next_changed"]=getattr(r2,"changed",None); R["L01_status2"]=i.status
try:
    s=i.get_persisted_snapshot(); R["L01_snapshot"]={"status":s["status"],"state_ids":s["state_ids"]}
except Exception as ex: R["L01_snapshot"]="REFUSED:"+type(ex).__name__

# LIB-01 onUnhandled:error receipt indistinguishable
cfg2={"id":"u","initial":"a","onUnhandled":"error","states":{"a":{"on":{"GO":"b"}},"b":{}}}
i2=SyncInterpreter(create_machine(cfg2,logic=MachineLogic())).start()
r=i2.send("NOPE")
R["LIB01_receipt"]=(getattr(r,"changed",None),repr(getattr(r,"error",None)),getattr(r,"deferred",None))
R["LIB01_status"]=i2.status; R["LIB01_interp_error"]=repr(i2.error)[:70]
R["LIB01_last_error"]=repr(getattr(i2,"last_error",None))

# L-02/C-03b guard-denied under onUnhandled:error
cfg3={"id":"g","initial":"a","onUnhandled":"error","states":{"a":{"on":{"GO":{"target":"b","guard":"no"}}},"b":{}}}
i3=SyncInterpreter(create_machine(cfg3,logic=MachineLogic(guards={"no":lambda c,e:False}))).start()
r=i3.send("GO")
R["C03b_receipt"]=(getattr(r,"changed",None),repr(getattr(r,"error",None)),getattr(r,"deferred",None))
R["C03b_status"]=i3.status; R["C03b_ids"]=sorted(i3.current_state_ids)
R["C03b_last_error"]=repr(getattr(i3,"last_error",None))

# D-observability-2: guard raise absorbed
for pol in ("raise",):
    cfg4={"id":"gr","initial":"a","guardErrorPolicy":pol,"states":{"a":{"on":{"GO":{"target":"b","guard":"bad"}}},"b":{}}}
    i4=SyncInterpreter(create_machine(cfg4,logic=MachineLogic(guards={"bad":gboom}))).start()
    try:
        r=i4.send("GO"); rcp=(getattr(r,"changed",None),repr(getattr(r,"error",None))[:50])
    except Exception as ex: rcp=("RAISED-AT-CALLSITE",type(ex).__name__)
    R["guardraise_"+pol]=(rcp,i4.status,repr(getattr(i4,"error",None))[:40],repr(getattr(i4,"last_error",None))[:40])

# J-3 inline plain-def service blocks async loop
async def j3():
    def slow(i,c,e): time.sleep(0.6); return 1
    c={"id":"s","initial":"a","states":{"a":{"invoke":{"src":"slow","onDone":"b"}},"b":{}}}
    m=create_machine(c,logic=MachineLogic(services={"slow":slow}))
    ticks=[0]
    async def tick():
        try:
            while True: await asyncio.sleep(0.01); ticks[0]+=1
        except asyncio.CancelledError: pass
    t=asyncio.ensure_future(tick()); await asyncio.sleep(0.05); ticks[0]=0
    t0=time.perf_counter(); it=await Interpreter(m).start(); d=time.perf_counter()-t0
    t.cancel(); await it.stop()
    return round(d,3), ticks[0]
R["J3_blocked_s"],R["J3_ticks"]=asyncio.run(j3())

# J-5 settle budget per drain
chain={"id":"ch","initial":"s0","maxIterations":50,"states":{}}
N=40
for k in range(N): chain["states"][f"s{k}"]={"on":{"GO":f"t{k}"} if k==0 else {}}
chain["states"]={"idle":{"on":{"A":"u0","B":"v0"}}}
for p in ("u","v"):
    for k in range(N): chain["states"][f"{p}{k}"]={"always":f"{p}{k+1}"} if k<N-1 else {}
    chain["states"][f"{p}{N-1}"]={}
chain["initial"]="idle"
m5=create_machine(chain,logic=MachineLogic())
i5=SyncInterpreter(m5).start()
i5.send("A"); R["J5_single_A"]=sorted(i5.current_state_ids)
i6=SyncInterpreter(create_machine(chain,logic=MachineLogic())).start()
try:
    i6.send_events("A","B") if hasattr(i6,"send_events") else None
except Exception as ex: R["J5_batch_err"]=type(ex).__name__
R["J5_batch_ids"]=sorted(i6.current_state_ids)
R["J5_batch_ok"]=getattr(i6,"last_transition_ok",None); R["J5_batch_lasterr"]=repr(getattr(i6,"last_error",None))[:60]

# D5-security-3: dict-shaped event accepted by send()
i7=SyncInterpreter(create_machine({"id":"d","initial":"a","states":{"a":{"on":{"GO":"b"}},"b":{}}},logic=MachineLogic())).start()
try:
    r=i7.send({"type":"GO"}); R["dictevent"]=("ACCEPTED",getattr(r,"changed",None),sorted(i7.current_state_ids))
except Exception as ex: R["dictevent"]=type(ex).__name__
print(json.dumps(R,indent=1,default=str))
