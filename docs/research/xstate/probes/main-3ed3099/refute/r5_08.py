"""R5-08 adversarial refutation: send_threadsafe self-feed vs maxIterations."""
from __future__ import annotations
import asyncio, json, logging, sys, threading, time
sys.path.insert(0, r"<workspace>/_ref/xstate-statemachine")
from src.xstate_statemachine import Interpreter, MachineLogic, create_machine
from src.xstate_statemachine.plugins import PluginBase

OUT = {}
POLICY = {
    "actionErrorPolicy": "rollback", "onUnhandled": "defer",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "spawnBlockingTimeout": 5000,
}

class Drops(PluginBase):
    def __init__(self): self.d = []
    def on_event_dropped(self, i, e, reason): self.d.append((e.type, reason))

def cfg(**extra):
    c = {"id": "spin", "initial": "a", "maxIterations": 20, "context": {"n": 0},
         **POLICY, "states": {"a": {"on": {"T": {"actions": ["r"]}}}}}
    c.update(extra); return c

# A: faithful repro, WITH the mandatory policy block
async def a_repro():
    seen = {"n": 0}
    def act(i, c, e, a):
        seen["n"] += 1
        if seen["n"] < 60:
            threading.Thread(target=lambda: i.send_threadsafe("T"), daemon=True).start()
    d = Drops()
    i = Interpreter(create_machine(cfg(), logic=MachineLogic(actions={"r": act}))).use(d)
    await i.start(); await i.send("T"); await asyncio.sleep(1.5)
    OUT["A_count"] = seen["n"]; OUT["A_budgeted"] = seen["n"] <= 25
    OUT["A_drops"] = d.d[:3]; await i.stop()

# B: the SAME thread-identity logic applied to a GENUINE external producer
#    thread -> would the proposed fix regress #105?
async def b_external_producer_thread():
    """A real external producer thread sends 30 events while a slow action
    holds the step. Under the proposed 'count send_threadsafe while
    _processing' fix these would be charged to maxIterations."""
    seen = {"n": 0}
    async def slow(i, c, e, a): await asyncio.sleep(0.3)
    def inc(i, c, e, a): seen["n"] += 1
    c = {"id": "m", "initial": "a", "maxIterations": 10, **POLICY,
         "states": {"a": {"on": {"SLOW": {"actions": "slow"}, "T": {"actions": "inc"}}}}}
    d = Drops()
    i = Interpreter(create_machine(c, logic=MachineLogic(actions={"slow": slow, "inc": inc}))).use(d)
    await i.start()
    t = asyncio.ensure_future(i.send("SLOW"))
    await asyncio.sleep(0.02)
    th = threading.Thread(target=lambda: [i.send_threadsafe("T") for _ in range(30)], daemon=True)
    th.start(); th.join(); await t; await asyncio.sleep(0.5)
    OUT["B_external_thread_delivered"] = seen["n"]
    OUT["B_external_thread_drops"] = d.d[:3]
    await i.stop()

# C: is the machine STARVED by the unbudgeted thread loop, like a real
#    runaway chain? (a runaway chain blocks the inbox; inbox traffic does not)
async def c_starvation():
    seen = {"n": 0, "other": 0}
    def act(i, c, e, a):
        seen["n"] += 1
        if seen["n"] < 40:
            threading.Thread(target=lambda: i.send_threadsafe("T"), daemon=True).start()
    def other(i, c, e, a): seen["other"] += 1
    c = {"id": "s2", "initial": "a", "maxIterations": 20, **POLICY,
         "states": {"a": {"on": {"T": {"actions": ["r"]}, "OTHER": {"actions": ["o"]}}}}}
    i = await Interpreter(create_machine(c, logic=MachineLogic(actions={"r": act, "o": other}))).start()
    await i.send("T")
    for _ in range(5):
        await asyncio.sleep(0.02); await i.send("OTHER")
    await asyncio.sleep(1.0)
    OUT["C_self_count"] = seen["n"]; OUT["C_other_delivered"] = seen["other"]
    OUT["C_interleaved"] = seen["other"] == 5
    await i.stop()

# D: mitigation available to an OMS -- bounded inbox
async def d_bounded_inbox():
    from src.xstate_statemachine import OverflowPolicy
    seen = {"n": 0}
    def act(i, c, e, a):
        seen["n"] += 1
        if seen["n"] < 200:
            threading.Thread(target=lambda: i.send_threadsafe("T"), daemon=True).start()
    d = Drops()
    i = Interpreter(create_machine(cfg(id="bd"), logic=MachineLogic(actions={"r": act})),
                    max_queue_size=4, overflow_policy=OverflowPolicy.DROP_NEWEST).use(d)
    await i.start(); await i.send("T"); await asyncio.sleep(1.0)
    OUT["D_count"] = seen["n"]; OUT["D_queue_full_drops"] = sum(1 for _, r in d.d if r == "queue_full")
    await i.stop()

# E: does asyncio.to_thread (the idiomatic 'hand work to a worker') behave
#    like the raw Thread, or does it inherit context?
async def e_to_thread():
    seen = {"n": 0}
    async def act(i, c, e, a):
        seen["n"] += 1
        if seen["n"] < 60:
            asyncio.ensure_future(asyncio.to_thread(lambda: i.send_threadsafe("T")))
    i = await Interpreter(create_machine(cfg(id="tt"), logic=MachineLogic(actions={"r": act}))).start()
    await i.send("T"); await asyncio.sleep(1.5)
    OUT["E_to_thread_count"] = seen["n"]; OUT["E_to_thread_budgeted"] = seen["n"] <= 25
    await i.stop()

async def main():
    await a_repro(); await b_external_producer_thread(); await c_starvation()
    await d_bounded_inbox(); await e_to_thread()
    print(json.dumps(OUT, indent=2, default=str))

if __name__ == "__main__":
    logging.getLogger("src.xstate_statemachine.base_interpreter").setLevel(logging.CRITICAL)
    logging.getLogger("src.xstate_statemachine.interpreter").setLevel(logging.CRITICAL)
    asyncio.run(main())
