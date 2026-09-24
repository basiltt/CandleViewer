import asyncio, copy, logging, time, collections
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, MachineLogic, Interpreter
import xstate_statemachine.interpreter as I

CFG={"id":"m","initial":"a","maxIterations":1,
 "on":{"GO":{"target":"#m.a","internal":True}},
 "states":{"a":{"initial":"a","always":{"target":"#m.a.a","guard":"g"},
   "states":{"a":{"invoke":{"id":"i","src":"svc"}}}}}}
cnt=collections.Counter()
def lg():
    return MachineLogic(actions={},guards={"g":lambda c,e:True},
        services={"svc":lambda i,c,e:{"ok":1}})
orig=I.Interpreter._process_event
async def patched(self,event):
    cnt[event.type or "<always>"]+=1
    return await orig(self,event)
I.Interpreter._process_event=patched
async def m():
    it=Interpreter(create_machine(copy.deepcopy(CFG),logic=lg()),strict=False)
    await it.start(); await asyncio.sleep(0.05)
    cnt.clear()
    try: await asyncio.wait_for(it.send("GO",wait=True),timeout=3)
    except asyncio.TimeoutError: print("HANG")
    print(dict(cnt.most_common(8)), "total",sum(cnt.values()))
    print("qsize",it._event_queue.qsize(),"raise_depth",it._raise_depth)
    try: await asyncio.wait_for(it.stop(),timeout=3)
    except Exception: pass
asyncio.run(m())
