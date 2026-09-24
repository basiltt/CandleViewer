# STANDALONE: does the rollback+onDone cycle plateau, or spin forever?
# Usage: python t_r6_plateau.py [def|async]
import asyncio, sys, time, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, create_machine

KIND = sys.argv[1] if len(sys.argv) > 1 else "def"
CFG = {"id":"spin","actionErrorPolicy":"rollback","initial":"starting","context":{},
 "states":{"starting":{"invoke":{"id":"s","src":"svc","onDone":{"target":"#spin.recording"}}},
           "recording":{"entry":["boom"]}}}

async def main():
    calls=[0]
    def boom(*a): raise RuntimeError("boom")
    def bump(): calls[0]+=1; return 1
    if KIND=="def":
        def svc(*a): return bump()
    else:
        async def svc(*a): return bump()
    i=Interpreter(create_machine(CFG, logic=MachineLogic(actions={"boom":boom},services={"svc":svc})))
    await i.start()
    t0=time.monotonic(); series=[]
    # poll for up to 20s: record the count each 0.5s, stop once stable 6 reads
    stable=0; last=-1
    while time.monotonic()-t0 < 20:
        await asyncio.sleep(0.5)
        c=calls[0]; series.append((round(time.monotonic()-t0,2), c))
        if c==last: stable+=1
        else: stable=0
        last=c
        if stable>=5: break
    print(f"kind={KIND} status={i.status} final_calls={calls[0]}")
    print(f"series={series}")
    await i.stop()
    return calls[0], stable

n,stable = asyncio.run(main())
bounded = stable>=5
print(f"BOUNDED={bounded} plateau={n}")
sys.exit(0 if bounded else 1)
