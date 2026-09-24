import asyncio, gc, psutil, logging
logging.getLogger("xstate_statemachine").setLevel(logging.CRITICAL)
from xstate_statemachine import create_machine, Interpreter, MachineLogic
P=psutil.Process()
def rss(): return P.memory_info().rss/1e6
ORD={"id":"o","initial":"s","context":{"filled":0,"seen":[],"deferred":[]},
  "states":{"s":{"on":{"EXEC":{"target":"#o.s","reenter":True,"actions":["f"]}}}}}
def f(i,c,e,a): c["filled"]+=1
async def main():
    m=create_machine(ORD,logic=MachineLogic(actions={"f":f}))
    gc.collect(); b=rss()
    N=2854
    xs=[await Interpreter(m).start() for _ in range(N)]
    gc.collect(); a=rss()
    print(f"idle fleet N={N}: RSS {b:.1f} -> {a:.1f} MB  delta={a-b:.1f} MB  ({(a-b)*1000/N:.1f} KB each)")
    # churn burst: queue depth memory
    for x in xs[:1000]:
        for _ in range(20): await x.send("EXEC")
    gc.collect(); c=rss()
    print(f"after queueing 20k events (unbounded queue): RSS {c:.1f} MB (+{c-a:.1f} MB queued backlog)")
    await asyncio.sleep(1.5)
    gc.collect(); d=rss()
    print(f"after drain: RSS {d:.1f} MB")
    for x in xs: await x.stop()
    del xs; gc.collect(); await asyncio.sleep(0.2); gc.collect()
    print(f"after teardown+gc: RSS {rss():.1f} MB (retained {rss()-b:.1f} MB)")
asyncio.run(main())
