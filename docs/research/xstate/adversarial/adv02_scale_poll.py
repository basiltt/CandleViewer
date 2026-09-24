"""Adversarial: per-entity interpreter explosion + 5ms actor-poll tax + governor latency."""
import asyncio, gc, os, time, statistics as st, logging
logging.getLogger("xstate_statemachine").setLevel(logging.CRITICAL)
from xstate_statemachine import create_machine, Interpreter, MachineLogic
try:
    import psutil; P=psutil.Process()
    rss=lambda: P.memory_info().rss/1e6
except Exception:
    rss=lambda: float('nan')

CHILD={"id":"leg","initial":"w","context":{},"states":{"w":{"on":{"DONE":{"target":"#leg.d"}}},"d":{"type":"final"}}}
PARENT={"id":"grp","initial":"idle","context":{},
 "states":{"idle":{"on":{"GO":{"target":"#grp.run"}}},
           "run":{"invoke":[{"id":f"c{i}","src":"leg_src","onDone":{"target":"#grp.run"}} for i in range(1)]}}}

def mk_parent(n):
    return {"id":"grp","initial":"idle","context":{},
      "states":{"idle":{"on":{"GO":{"target":"#grp.run"}}},
                "run":{"invoke":[{"id":f"c{i}","src":"leg_src"} for i in range(n)]}}}

async def poll_tax():
    """Each invoked child machine = one task polling every 5ms. Measure loop impact."""
    child=create_machine(CHILD,logic=MachineLogic())
    out={}
    for nchild in (0,50,200):
        m=create_machine(mk_parent(nchild),logic=MachineLogic(services={"leg_src":child}))
        i=await Interpreter(m).start()
        if nchild: await i.send("GO")
        await asyncio.sleep(0.4)
        # measure event-loop jitter while children poll
        lat=[]
        for _ in range(200):
            t=time.perf_counter(); await asyncio.sleep(0)
            lat.append((time.perf_counter()-t)*1e6)
        # measure sleep(0.005) drift = scheduler pressure
        drift=[]
        for _ in range(40):
            t=time.perf_counter(); await asyncio.sleep(0.005)
            drift.append((time.perf_counter()-t-0.005)*1e3)
        out[nchild]=(st.median(lat), st.median(drift), max(drift))
        await i.stop()
    print("[actor_poll_tax] children -> (median sleep(0) us, median 5ms drift ms, max drift ms)")
    for k,v in out.items(): print(f"   {k:>4}: sleep0={v[0]:.1f}us  drift_p50={v[1]:.2f}ms  drift_max={v[2]:.2f}ms")

async def fleet():
    """Realistic worst case: 500 orders + 50 groups x 10 legs + 50 algos x 12 slices."""
    ORD={"id":"o","initial":"s","context":{"filled":0},
      "states":{"s":{"on":{"EXEC":{"target":"#o.s","reenter":True,"actions":["f"]}}}}}
    def f(i,c,e,a): c["filled"]+=1
    logic=MachineLogic(actions={"f":f})
    m=create_machine(ORD,logic=logic)
    gc.collect(); base=rss()
    counts={"order":500,"leg":50*10,"algo_slice":50*12,"rule":1000,"protection":100,
            "session":20,"conn":10,"book":24,"recon":25,"lockout":25,"alert":50}
    total=sum(counts.values())
    interps=[]
    t0=time.perf_counter()
    for _ in range(total):
        interps.append(await Interpreter(m).start())
    build=time.perf_counter()-t0
    gc.collect(); after=rss()
    print(f"\n[fleet] total interpreters={total} (breakdown {counts})")
    print(f"   start cost={build*1e3:.0f} ms  ({build/total*1e6:.1f} us each)")
    print(f"   RSS delta={after-base:.1f} MB  ({(after-base)*1000/total:.1f} KB each)")
    # saturate: OMS-critical latency while the whole fleet churns
    stop=False
    async def churn(ix):
        while not stop:
            await ix.send("EXEC")
            await asyncio.sleep(0)
    bg=[asyncio.create_task(churn(x)) for x in interps[:600]]
    await asyncio.sleep(0.3)
    target=interps[-1]
    lat=[]
    for _ in range(60):
        n0=target.context["filled"]; t=time.perf_counter()
        await target.send("EXEC")
        while target.context["filled"]==n0: await asyncio.sleep(0)
        lat.append((time.perf_counter()-t)*1e3)
    stop=True
    for b in bg: b.cancel()
    await asyncio.gather(*bg,return_exceptions=True)
    lat.sort()
    print(f"   KILL-SWITCH/critical event latency under fleet churn: p50={lat[len(lat)//2]:.1f}ms "
          f"p95={lat[int(len(lat)*.95)]:.1f}ms max={lat[-1]:.1f}ms")
    for x in interps: await x.stop()

async def main():
    await poll_tax(); await fleet()
asyncio.run(main())
