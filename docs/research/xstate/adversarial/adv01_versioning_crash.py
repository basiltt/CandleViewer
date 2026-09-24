"""Adversarial probes: machine-JSON versioning, crash mid-transition, queue durability."""
import asyncio, json, logging, sys
logging.getLogger("xstate_statemachine").setLevel(logging.CRITICAL)
from xstate_statemachine import create_machine, Interpreter, MachineLogic

R = {}

V1 = {"id":"ord","initial":"draft","context":{"qty":0,"filled":0},
 "states":{
  "draft":{"on":{"SEND":{"target":"#ord.submitted"}}},
  "submitted":{"on":{"FILL":{"target":"#ord.filled","actions":["apply"]}}},
  "filled":{"type":"final"}}}

# v2: renamed 'submitted' -> 'working'; added context key; removed 'filled' ctx key
V2 = {"id":"ord","initial":"draft","context":{"qty":0,"cum_qty":0,"venue":None},
 "states":{
  "draft":{"on":{"SEND":{"target":"#ord.working"}}},
  "working":{"on":{"FILL":{"target":"#ord.filled","actions":["apply"]}}},
  "filled":{"type":"final"}}}

def apply(i,c,e,a): c["filled"]=c.get("filled",0)+1

async def t1_rename():
    logic=MachineLogic(actions={"apply":apply})
    m1=create_machine(V1,logic=logic); m2=create_machine(V2,logic=logic)
    i=await Interpreter(m1).start(); await i.send("SEND"); await asyncio.sleep(0.05)
    snap=i.get_snapshot(); await i.stop()
    try:
        j=Interpreter.from_snapshot(snap,m2)
        R["rename_state_restore"]=f"NO ERROR -> states={sorted(j.current_state_ids)}"
    except Exception as ex:
        R["rename_state_restore"]=f"{type(ex).__name__}: {ex}"

async def t2_ctx_drift():
    """Same state ids, but context schema changed. Does restore notice?"""
    V2b=json.loads(json.dumps(V1)); V2b["context"]={"qty":0,"cum_qty":0,"venue":"bybit"}
    logic=MachineLogic(actions={"apply":apply})
    m1=create_machine(V1,logic=logic); m2=create_machine(V2b,logic=logic)
    i=await Interpreter(m1).start(); await i.send("SEND"); await asyncio.sleep(0.05)
    snap=i.get_snapshot(); await i.stop()
    j=Interpreter.from_snapshot(snap,m2)
    await j.start(); await j.send("FILL"); await asyncio.sleep(0.05)
    R["ctx_drift_restore"]=(f"restored ctx={j.context} (new default keys cum_qty/venue "
        f"{'PRESENT' if 'venue' in j.context else 'MISSING'}) states={sorted(j.current_state_ids)}")
    await j.stop()

async def t3_semantic_drift():
    """Same state id, DIFFERENT meaning (guard added). Restore is silent."""
    V3=json.loads(json.dumps(V1))
    V3["states"]["submitted"]["on"]["FILL"]={"target":"#ord.filled","guard":"never","actions":["apply"]}
    logic1=MachineLogic(actions={"apply":apply})
    logic2=MachineLogic(actions={"apply":apply},guards={"never":lambda c,e:False})
    m1=create_machine(V1,logic=logic1); m3=create_machine(V3,logic=logic2)
    i=await Interpreter(m1).start(); await i.send("SEND"); await asyncio.sleep(0.05)
    snap=i.get_snapshot(); await i.stop()
    j=Interpreter.from_snapshot(snap,m3); await j.start()
    await j.send("FILL"); await asyncio.sleep(0.05)
    R["semantic_drift"]=f"restored into v3 silently; after FILL states={sorted(j.current_state_ids)} (order now stuck)"
    await j.stop()

async def t4_queue_loss():
    """Crash simulation: events queued but not yet processed when we snapshot/stop."""
    slow_calls=[]
    def slow(i,c,e,a):
        slow_calls.append(e.type)
    M={"id":"q","initial":"a","context":{"n":0},
       "states":{"a":{"on":{"E":{"actions":["bump"],"target":"#q.a","reenter":True}}}}}
    async def svc(i,c,e): await asyncio.sleep(5)
    def bump(i,c,e,a):
        c["n"]+=1
    m=create_machine(M,logic=MachineLogic(actions={"bump":bump}))
    i=await Interpreter(m).start()
    for _ in range(50): await i.send("E")
    snap_before_drain=json.loads(i.get_snapshot())
    await i.stop()
    R["queue_loss"]=(f"50 events sent; snapshot taken immediately shows n={snap_before_drain['context']['n']}; "
                     f"context after stop n={i.context['n']}; "
                     f"{50-i.context['n']} events LOST on stop (never processed, not in snapshot)")

async def t5_mid_transition_crash():
    """Action list [persist, explode, notify]: what is durable vs lost."""
    trace=[]
    def persist(i,c,e,a): trace.append("persist"); c["persisted"]=True
    def explode(i,c,e,a): trace.append("explode"); raise RuntimeError("boom")
    def notify(i,c,e,a): trace.append("notify"); c["notified"]=True
    M={"id":"x","initial":"a","context":{},
       "states":{"a":{"on":{"GO":{"target":"#x.b","actions":["persist","explode","notify"]}}},
                 "b":{"entry":["mark_b"]}}}
    def mark_b(i,c,e,a): trace.append("entry_b"); c["in_b"]=True
    m=create_machine(M,logic=MachineLogic(actions={"persist":persist,"explode":explode,"notify":notify,"mark_b":mark_b}))
    i=await Interpreter(m).start(); await i.send("GO"); await asyncio.sleep(0.05)
    snap=json.loads(i.get_snapshot())
    R["mid_transition_crash"]=(f"trace={trace}; states={sorted(i.current_state_ids)}; status={i.status}; "
        f"SNAPSHOT PERSISTS THE BROKEN STATE: {snap['state_ids']} ctx={snap['context']}")
    await i.stop()

async def main():
    for f in (t1_rename,t2_ctx_drift,t3_semantic_drift,t4_queue_loss,t5_mid_transition_crash):
        try: await f()
        except Exception as ex: R[f.__name__]=f"PROBE ERROR {type(ex).__name__}: {ex}"
    for k,v in R.items(): print(f"[{k}]\n  {v}\n")

asyncio.run(main())
