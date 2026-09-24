"""Adversarial: task count per actor, governor-as-statechart latency, terminal-machine leak."""
import asyncio, time, logging, statistics as st
logging.getLogger("xstate_statemachine").setLevel(logging.CRITICAL)
from xstate_statemachine import create_machine, Interpreter, MachineLogic

CHILD={"id":"leg","initial":"w","context":{},"states":{"w":{"on":{"X":{"target":"#leg.d"}}},"d":{"type":"final"}}}

def mk(n): return {"id":"g","initial":"i","context":{},
  "states":{"i":{"on":{"GO":{"target":"#g.r"}}},"r":{"invoke":[{"id":f"c{k}","src":"leg_src"} for k in range(n)]}}}

async def tasks_per_actor():
    child=create_machine(CHILD,logic=MachineLogic())
    print("[tasks_per_actor] asyncio.Task count vs invoked children (each child = 1 poll task @5ms)")
    for n in (0,10,50,200):
        m=create_machine(mk(n),logic=MachineLogic(services={"leg_src":child}))
        i=await Interpreter(m).start()
        base=len(asyncio.all_tasks())
        if n: await i.send("GO")
        await asyncio.sleep(0.3)
        print(f"   children={n:>4} tasks={len(asyncio.all_tasks()):>4} (delta {len(asyncio.all_tasks())-base})")
        await i.stop()

async def governor():
    """Rate-limit governor as a statechart: can it make a 4 req/s admit decision synchronously?"""
    G={"id":"gov","initial":"open","context":{"tokens":4},
       "states":{"open":{"on":{"RESERVE":[
            {"target":"#gov.open","reenter":True,"guard":"has_token","actions":["take"]},
            {"target":"#gov.starved"}]}},
         "starved":{"on":{"REFILL":{"target":"#gov.open","actions":["refill"]}}}}}
    def take(i,c,e,a): c["tokens"]-=1
    def refill(i,c,e,a): c["tokens"]=4
    m=create_machine(G,logic=MachineLogic(actions={"take":take,"refill":refill},
                                          guards={"has_token":lambda c,e:c["tokens"]>0}))
    gov=await Interpreter(m).start()
    # background load: 500 order machines churning
    ORD={"id":"o","initial":"s","context":{"n":0},"states":{"s":{"on":{"E":{"target":"#o.s","reenter":True,"actions":["f"]}}}}}
    def f(i,c,e,a): c["n"]+=1
    om=create_machine(ORD,logic=MachineLogic(actions={"f":f}))
    xs=[await Interpreter(om).start() for _ in range(500)]
    stop=False
    async def churn(x):
        while not stop:
            await x.send("E"); await asyncio.sleep(0)
    bg=[asyncio.create_task(churn(x)) for x in xs]
    await asyncio.sleep(0.3)
    lat=[]
    for _ in range(50):
        gov.context["tokens"]=4
        t=time.perf_counter(); await gov.send("RESERVE")
        while gov.context["tokens"]==4: await asyncio.sleep(0)
        lat.append((time.perf_counter()-t)*1e3)
    stop=True
    for b in bg: b.cancel()
    await asyncio.gather(*bg,return_exceptions=True)
    lat.sort()
    # compare: plain python token bucket
    toks=[4]
    t=time.perf_counter()
    for _ in range(50000):
        if toks[0]>0: toks[0]-=1
        else: toks[0]=4
    plain=(time.perf_counter()-t)/50000*1e6
    print(f"\n[governor] statechart RESERVE decision under 500-machine churn: "
          f"p50={lat[len(lat)//2]:.2f}ms p95={lat[int(len(lat)*.95)]:.2f}ms max={lat[-1]:.2f}ms")
    print(f"   plain-python token bucket decision: {plain:.3f} us  -> statechart is ~{lat[len(lat)//2]*1000/plain:,.0f}x slower")
    print(f"   NOTE: admission control is called PRE-FLIGHT on the order path (20 §4.3); it must be synchronous.")
    for x in xs: await x.stop()
    await gov.stop()

async def terminal_leak():
    """Does a machine that reaches a final state stop itself / free its task?"""
    M={"id":"t","initial":"a","context":{},"states":{"a":{"on":{"E":{"target":"#t.z"}}},"z":{"type":"final"}}}
    m=create_machine(M,logic=MachineLogic())
    i=await Interpreter(m).start()
    await i.send("E"); await asyncio.sleep(0.05)
    print(f"\n[terminal_leak] after reaching final: status={i.status} is_running={i.is_running} "
          f"tasks_alive={sum(1 for t in asyncio.all_tasks() if not t.done())}")
    print(f"   -> terminal machines must be explicitly stop()'d and evicted by US; nothing reaps them.")
    await i.stop()

async def main():
    await tasks_per_actor(); await governor(); await terminal_leak()
asyncio.run(main())
