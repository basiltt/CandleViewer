"""Adversarial: does the mandated deferral workaround (A3) actually hold under crash + reorder?"""
import asyncio, json, logging
logging.getLogger("xstate_statemachine").setLevel(logging.CRITICAL)
from xstate_statemachine import create_machine, Interpreter, MachineLogic

M={"id":"o","initial":"submitting","context":{"filled":0,"_deferred":[],"seen":[]},
 "states":{
  "submitting":{"invoke":{"id":"p","src":"place","onDone":{"target":"#o.submitted"}},
                "on":{"*":{"actions":["defer"]}}},
  "submitted":{"entry":["drain"],"on":{"EXEC":{"actions":["apply"]}}}}}

async def place(i,c,e): await asyncio.sleep(0.25); return {"ok":True}
def defer(i,c,e,a):
    if e.type.startswith(("done.","error.","xstate.")): return
    c["_deferred"].append({"type":e.type,"payload":dict(e.payload)})
def apply(i,c,e,a):
    x=e.payload.get("exec_id")
    if x in c["seen"]: return
    c["seen"].append(x); c["filled"]+=1
def drain(i,c,e,a):
    d=c["_deferred"]; c["_deferred"]=[]
    for ev in d: asyncio.create_task(i.send(ev["type"],**ev["payload"]))

async def t_ok():
    m=create_machine(M,logic=MachineLogic(actions={"defer":defer,"apply":apply,"drain":drain},services={"place":place}))
    i=await Interpreter(m).start()
    for k in range(3): await i.send("EXEC",exec_id=f"e{k}")
    await asyncio.sleep(0.6)
    print(f"[defer_happy_path] filled={i.context['filled']} seen={i.context['seen']} (expect 3)")
    await i.stop()

async def t_crash():
    """Crash while events sit in _deferred AND in the interpreter queue."""
    m=create_machine(M,logic=MachineLogic(actions={"defer":defer,"apply":apply,"drain":drain},services={"place":place}))
    i=await Interpreter(m).start()
    for k in range(3): await i.send("EXEC",exec_id=f"e{k}")
    await asyncio.sleep(0.05)   # deferred, invoke still in flight
    snap=i.get_snapshot()
    await i.stop()              # "crash"
    s=json.loads(snap)
    print(f"[defer_crash] snapshot state={s['state_ids']} _deferred={s['context']['_deferred']}")
    j=Interpreter.from_snapshot(snap,m); await j.start(); await asyncio.sleep(0.6)
    print(f"   after restore+start: state={sorted(j.current_state_ids)} filled={j.context['filled']} "
          f"_deferred_still={len(j.context['_deferred'])}")
    print("   -> invoke NOT restarted, so drain never runs; deferred fills are PERSISTED BUT NEVER APPLIED "
          "unless our boot procedure re-drives the invoke state.")
    await j.stop()

async def t_reorder():
    """drain uses create_task(send) -> do drained events keep order vs a concurrently arriving live event?"""
    order=[]
    def apply2(i,c,e,a): order.append(e.payload.get("exec_id"))
    mm=json.loads(json.dumps(M))
    m=create_machine(mm,logic=MachineLogic(actions={"defer":defer,"apply":apply2,"drain":drain},services={"place":place}))
    i=await Interpreter(m).start()
    for k in range(3): await i.send("EXEC",exec_id=f"old{k}")
    await asyncio.sleep(0.24)
    await i.send("EXEC",exec_id="LIVE")   # arrives right at the transition boundary
    await asyncio.sleep(0.5)
    print(f"\n[defer_reorder] delivery order = {order}")
    print("   -> exchange (ts_exec,seq) ordering is NOT preserved by the defer/drain workaround; "
          "actions must re-sort by (ts_exec,seq), never trust arrival order.")
    await i.stop()

async def main():
    await t_ok(); await t_crash(); await t_reorder()
asyncio.run(main())
