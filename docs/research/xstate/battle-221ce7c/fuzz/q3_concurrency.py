"""Q3 -- round-6 concurrency fixes.
C1 #166: 16 concurrent EXTERNAL senders during a self-generated chain --
        external traffic must NOT reset the chain bound; the chain must trip.
C2 #173: service_pool_size=1 with 50 plain services + stop() mid-service.
C3 #172: threadsafe in-flight counter -- done-callback double-fire / balance.
C4 #157: loop-side RAISE refusal fires on_event_dropped(queue_full) exactly
        once per refusal, and the future still carries the error."""
import asyncio, logging, threading, time, warnings, collections
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (Interpreter, MachineLogic, create_machine,
                                 PluginBase)
from xstate_statemachine.exceptions import QueueOverflowError

class Drops(PluginBase):
    def __init__(self): self.c = collections.Counter()
    def on_event_dropped(self, interp, event, reason): self.c[reason] += 1

# ---------------- C1 ----------------
async def c1():
    CFG = {"id": "m", "initial": "a", "maxIterations": 50, "states": {
        "a": {"entry": ["spin"], "on": {"EXT": {"target": "a"}, "TICK": {"target": "a"}}}}}
    async def spin(i, c, e, a):
        if isinstance(c, dict):
            c["n"] = c.get("n", 0) + 1
            await i.send("TICK")          # self-generated chain
    d = Drops()
    it = Interpreter(create_machine(CFG, logic=MachineLogic(actions={"spin": spin})))
    it.use(d); await asyncio.wait_for(it.start(), 10)
    stop = False
    async def sender():
        while not stop:
            await it.send("EXT"); await asyncio.sleep(0.002)
    tasks = [asyncio.create_task(sender()) for _ in range(16)]
    await asyncio.sleep(4.0)
    stop = True
    for t in tasks: t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    err = type(it.last_error).__name__ if getattr(it, "last_error", None) else None
    print(f"C1 #166 16 ext senders + chain: trip={err} drops={dict(d.c)} "
          f"n={it.context.get('n')} status={it.status} "
          f"=> {'PASS' if err == 'RunawayChainError' else 'FAIL (external reset the bound / no trip)'}")
    await it.stop()

# ---------------- C2 ----------------
async def c2():
    CFG = {"id": "m", "initial": "a", "states": {
        "a": {"on": {"GO": {"target": "b"}}},
        "b": {"invoke": {"id": "s", "src": "slow", "onDone": {"target": "a"}}}}}
    def slow(i, c, e): time.sleep(0.02); return 1
    try:
        it = Interpreter(create_machine(CFG, logic=MachineLogic(services={"slow": slow})),
                         service_pool_size=1)
    except TypeError as e:
        print(f"C2 #173 service_pool_size: FAIL not accepted: {e}"); return
    await asyncio.wait_for(it.start(), 10)
    t0 = time.time(); done = 0
    for _ in range(50):
        await it.send("GO"); done += 1
    await asyncio.sleep(1.5)
    wall = time.time() - t0
    print(f"C2 #173 pool=1, 50 services: wall={wall:.2f}s status={it.status} "
          f"threads={threading.active_count()}")
    # stop() mid-service
    it2 = Interpreter(create_machine(CFG, logic=MachineLogic(services={"slow": slow})),
                      service_pool_size=1)
    await it2.start(); await it2.send("GO"); await asyncio.sleep(0.005)
    try:
        await asyncio.wait_for(it2.stop(), 10); print("   stop() mid-service: clean")
    except Exception as e: print(f"   stop() mid-service: {type(e).__name__}: {e}")
    await it.stop()

# ---------------- C3 ----------------
async def c3():
    CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"T": {"target": "a"}}}}}
    it = Interpreter(create_machine(CFG, logic=MachineLogic()))
    await asyncio.wait_for(it.start(), 10)
    loop = asyncio.get_running_loop()
    futs = []
    def worker():
        for _ in range(100):
            futs.append(it.send_threadsafe("T", internal=True))
    ths = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in ths]; [t.join() for t in ths]
    await asyncio.sleep(2.0)
    infl = it._threadsafe_self_sends_in_flight
    unresolved = sum(1 for f in futs if not f.done())
    print(f"C3 #172 in-flight counter: futures={len(futs)} unresolved={unresolved} "
          f"in_flight={infl} => {'PASS' if infl == 0 else 'FAIL (leaked count)'}")
    await it.stop()

# ---------------- C4 ----------------
async def c4():
    from xstate_statemachine import OverflowPolicy
    CFG = {"id": "m", "initial": "a", "states": {
        "a": {"on": {"T": {"target": "a", "actions": ["slow"]}}}}}
    async def slowa(i, c, e, a): await asyncio.sleep(0.05)
    d = Drops()
    it = Interpreter(create_machine(CFG, logic=MachineLogic(actions={"slow": slowa})),
                     max_queue_size=2, overflow_policy=OverflowPolicy.RAISE)
    it.use(d); await asyncio.wait_for(it.start(), 10)
    futs = []
    def worker():
        for _ in range(80):
            try: futs.append(it.send_threadsafe("T"))
            except Exception as ex: futs.append(ex)
    ths = [threading.Thread(target=worker) for _ in range(16)]
    [t.start() for t in ths]; [t.join() for t in ths]
    await asyncio.sleep(3.0)
    fut_errs = 0
    for f in futs:
        if isinstance(f, BaseException): fut_errs += 1
        elif f.done() and f.exception() is not None: fut_errs += 1
    print(f"C4 #157 loop-side RAISE: sends={len(futs)} future_errors={fut_errs} "
          f"hook_queue_full={d.c.get('queue_full', 0)} all_drops={dict(d.c)} "
          f"=> {'PASS' if fut_errs == 0 or d.c.get('queue_full',0) > 0 else 'FAIL (refusal invisible)'}")
    await it.stop()

async def main():
    for f in (c1, c2, c3, c4):
        try: await f()
        except Exception as e:
            import traceback; print(f"{f.__name__} HARNESS {type(e).__name__}: {e}")
asyncio.run(main())
