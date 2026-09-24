import asyncio, json, sys, threading, logging
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.models import OverflowPolicy

CFG={"id":"ts","initial":"s","context":{"n":0},"states":{"s":{"on":{"A":{"actions":["rec"]},"B":{"actions":["rec"]},"PING":{"actions":["inc"]}}}}}
def mk(order):
    def rec(i,c,e,a): order.append(f"{e.type}{e.payload['k']}")
    def inc(i,c,e,a): c["n"]=c["n"]+1
    return Interpreter(create_machine(CFG,logic=MachineLogic(actions={"rec":rec,"inc":inc})))

async def alternating_with_result(n=20):
    order=[]; interp=mk(order); await interp.start()
    a=threading.Event(); b=threading.Event()
    def th():
        for k in range(n):
            interp.send_threadsafe("A",k=k).result()   # documented: block until QUEUED
            a.set()
            while not b.is_set(): pass
            b.clear()
    t=threading.Thread(target=th); t.start()
    for k in range(n):
        while not a.is_set(): await asyncio.sleep(0)
        a.clear(); await interp.send("B",k=k); b.set()
    t.join()
    for _ in range(100000):
        if len(order)>=2*n: break
        await asyncio.sleep(0)
    await interp.stop()
    exp=[x for k in range(n) for x in (f"A{k}",f"B{k}")]
    return {"fifo":order==exp,"head":order[:10]}

async def backpressure_with_result(policy,cap=100,threads=8,each=100):
    interp=mk([]); interp=Interpreter(create_machine(CFG,logic=MachineLogic(actions={"rec":lambda *a:None,"inc":lambda i,c,e,a:c.update(n=c["n"]+1)})),max_queue_size=cap,overflow_policy=policy)
    await interp.start()
    raised=[0]; ok=[0]
    def prod():
        for _ in range(each):
            try:
                interp.send_threadsafe("PING").result(timeout=10); ok[0]+=1
            except Exception: raised[0]+=1
    ts=[threading.Thread(target=prod) for _ in range(threads)]
    for t in ts: t.start()
    while any(t.is_alive() for t in ts): await asyncio.sleep(0.005)
    await asyncio.sleep(0.3)
    out={"policy":policy.value,"raised_on_calling_thread_via_result":raised[0],"ok":ok[0],"processed":interp.context["n"]}
    await interp.stop(drain=True,timeout=30); return out

async def main():
    r={"alternating_with_result":[await alternating_with_result() for _ in range(6)],
       "backpressure_raise":await backpressure_with_result(OverflowPolicy.RAISE)}
    print(json.dumps(r,indent=1))
asyncio.run(main())
