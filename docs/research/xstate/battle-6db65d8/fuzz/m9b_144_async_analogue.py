import asyncio, copy, logging, time
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, MachineLogic, Interpreter, SyncInterpreter
# #144-shaped: nested invoke whose onDone re-enters the common ancestor. No `always`.
CFG={"id":"m","initial":"p","maxIterations":20,
 "on":{"GO":{"target":"#m.p"}},
 "states":{"p":{"initial":"w","states":{"w":{"invoke":{"id":"i","src":"svc",
    "onDone":{"target":"#m.p"}}}}}}}
def lg(): return MachineLogic(actions={},guards={},services={"svc":lambda i,c,e:{"ok":1}})
async def m():
    it=Interpreter(create_machine(copy.deepcopy(CFG),logic=lg()),strict=False)
    t=time.time()
    try: await asyncio.wait_for(it.start(),timeout=4)
    except asyncio.TimeoutError: print("async start HANG (#144 async analogue)"); return
    await asyncio.sleep(0.5)
    print("async start ok",sorted(it.current_state_ids),"err",type(getattr(it,'_last_action_error',None)).__name__)
    try: await asyncio.wait_for(it.send("GO",wait=True),timeout=4)
    except asyncio.TimeoutError: print("async send HANG")
    else: print("async send ok")
    try: await asyncio.wait_for(it.stop(),timeout=3)
    except Exception: pass
asyncio.run(m())
it=SyncInterpreter(create_machine(copy.deepcopy(CFG),logic=lg()))
t=time.time(); it.start()
print("sync start returned",f"{time.time()-t:.2f}s","err",type(getattr(it,'last_error',None)).__name__)
