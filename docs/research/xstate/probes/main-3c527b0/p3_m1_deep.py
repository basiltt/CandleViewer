import asyncio
from xstate_statemachine import Interpreter, create_machine, MachineLogic
CFG={"id":"gate","initial":"closed","onUnhandled":"defer","context":{"filled":0},
 "states":{"closed":{"on":{"OPEN":"open"}},
           "open":{"on":{"FILL":{"target":"filled","actions":["mark"]}}},
           "filled":{}}}
def mark(i,ctx,e,ad=None): ctx["filled"]+=1
L=lambda: MachineLogic(actions={"mark":mark})
async def main():
    # variant 1: plain defer, wait=True
    i=Interpreter(create_machine(CFG,logic=L())); await i.start()
    r=await i.send("FILL",wait=True)
    print("V1 defer receipt:",dict(changed=r.changed,error=r.error,
          deferred=getattr(i,'deferred_count',None)))
    await i.send("OPEN"); await asyncio.sleep(0.05)
    print("   after OPEN:",i.current_state_ids,i.context)
    await i.stop()
    # variant 2: does the receipt carry any new field distinguishing defer?
    print("V2 Receipt fields:", r._fields if hasattr(r,'_fields') else vars(r))
    # variant 3: a *handled* no-op event (true negative) -- same receipt?
    CFG3=dict(CFG); 
    j=Interpreter(create_machine({**CFG,"states":{**CFG["states"],
        "closed":{"on":{"OPEN":"open","NOOP":{"actions":[]}}}}},logic=L()))
    await j.start()
    r3=await j.send("NOOP",wait=True)
    print("V3 true-negative receipt:",dict(changed=r3.changed,error=r3.error,
          deferred=getattr(j,'deferred_count',None)))
    print("   => distinguishable only via deferred_count:",
          getattr(i,'deferred_count',None),"vs",getattr(j,'deferred_count',None))
    await j.stop()
    # variant 4: defer then replay -- is a SECOND receipt issued?
    k=Interpreter(create_machine(CFG,logic=L())); await k.start()
    rk=await k.send("FILL",wait=True)
    await k.send("OPEN"); await asyncio.sleep(0.05)
    print("V4 post-replay: same receipt object changed=",rk.changed,
          " state=",k.current_state_ids," ctx=",k.context)
    await k.stop()
asyncio.run(main())
