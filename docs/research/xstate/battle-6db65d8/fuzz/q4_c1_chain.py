"""Q4 -- C1 redone. A genuine self-generated RAISE chain (action re-sends its
own trigger) while 16 external senders hammer the inbox. Contract (#166/#151):
external events must NOT hand the chain a fresh budget; the chain must trip
with RunawayChainError + on_event_dropped(chain_budget)."""
import asyncio, logging, warnings, collections
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, create_machine, PluginBase

class Drops(PluginBase):
    def __init__(self): self.c = collections.Counter()
    def on_event_dropped(self, interp, event, reason): self.c[reason] += 1

CFG = {"id": "m", "initial": "a", "maxIterations": 50, "states": {"a": {
    "on": {"TICK": {"target": "a", "actions": ["again"]},
           "EXT":  {"target": "a", "actions": ["noop"]}}}}}

async def run(n_senders, label):
    async def again(i, c, e, a):
        c["n"] = c.get("n", 0) + 1
        await i.send("TICK")                    # self-generated
    async def noop(i, c, e, a):
        c["ext"] = c.get("ext", 0) + 1
    d = Drops()
    it = Interpreter(create_machine(dict(CFG),
        logic=MachineLogic(actions={"again": again, "noop": noop})))
    it.use(d); await asyncio.wait_for(it.start(), 10)
    stop = [False]
    async def sender():
        while not stop[0]:
            await it.send("EXT"); await asyncio.sleep(0.001)
    tasks = [asyncio.create_task(sender()) for _ in range(n_senders)]
    await it.send("TICK")                       # ignite the chain
    await asyncio.sleep(3.0)
    stop[0] = True
    for t in tasks: t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    err = type(it.last_error).__name__ if getattr(it, "last_error", None) else None
    n = it.context.get("n", 0)
    ok = err == "RunawayChainError" and d.c.get("chain_budget", 0) > 0
    print(f"  {label:<26} senders={n_senders:>2} chain_laps={n:>7} ext={it.context.get('ext',0):>6} "
          f"trip={err} drops={dict(d.c)} => {'PASS' if ok else 'FAIL'}")
    await it.stop()
    return n

async def main():
    print("== #166: external traffic must not reset the chain bound (limit=50) ==")
    base = await run(0, "quiet baseline")
    under = await run(16, "16 concurrent externals")
    print(f"  chain laps quiet={base} vs under-load={under}: "
          f"{'BOUNDED both' if max(base, under) < 5000 else 'UNBOUNDED under load'}")
asyncio.run(main())
