"""Adversarial: does the 'pre-filter' mitigation actually rescue the rule budget?"""
import asyncio, time, logging
logging.getLogger("xstate_statemachine").setLevel(logging.CRITICAL)
from xstate_statemachine import create_machine, Interpreter, MachineLogic

RULE={"id":"r","initial":"armed","context":{"fires":0},
 "states":{"armed":{"on":{"TRIGGER":[
     {"target":"#r.fired","guard":"cond"},
     {"target":"#r.armed","reenter":True}]}},
   "fired":{"entry":["bump"],"on":{"RESET":{"target":"#r.armed"}}}}}

async def main():
    def bump(i,c,e,a): c["fires"]+=1
    m=create_machine(RULE,logic=MachineLogic(actions={"bump":bump},guards={"cond":lambda c,e:False}))
    N=1000
    xs=[await Interpreter(m).start() for _ in range(N)]
    # aggregate throughput at realistic fleet size
    EV=30000
    t=time.perf_counter()
    for k in range(EV):
        await xs[k%N].send("TRIGGER")
    # drain
    while any(x._event_queue.qsize() if hasattr(x,'_event_queue') else 0 for x in xs[:50]):
        await asyncio.sleep(0.01)
    await asyncio.sleep(1.0)
    el=time.perf_counter()-t
    print(f"[fleet_throughput] {N} rule machines, {EV} events: {EV/el:,.0f} ev/s aggregate")
    # pre-filter hit-rate needed
    budget_evals = EV/el
    for hit in (1.0,0.1,0.05,0.01):
        need = 2000*100*hit
        print(f"   pre-filter hit-rate {hit*100:>5.1f}%: required {need:>9,.0f} machine-ev/s "
              f"-> {'OK' if need<budget_evals*0.4 else 'FAIL (>40% of whole process budget)'}")
    print(f"   NOTE: 40% of budget is the fit-analysis R3 alarm threshold (8k/s of ~20k).")
    # plain python comparison
    preds=[(lambda v,k=k: v>k) for k in range(100)]
    t=time.perf_counter()
    n=0
    for i in range(2000):
        for p in preds:
            if p(i): n+=1
    el2=time.perf_counter()-t
    print(f"   plain-python 200,000 predicate evals: {el2*1000:.0f} ms -> {200000/el2:,.0f} eval/s")
    for x in xs: await x.stop()
asyncio.run(main())
