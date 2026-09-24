"""Q8 -- hook matrix: chain_budget on BOTH engines, queue_full loop-side,
exactly-once, ordering. Each reason must fire exactly once per refusal and the
hook order must match the observable state change."""
import asyncio, collections, logging, threading, warnings, copy
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine, PluginBase, OverflowPolicy)

class Rec(PluginBase):
    def __init__(self): self.order = []; self.c = collections.Counter()
    def on_event_dropped(self, i, ev, reason):
        self.c[reason] += 1; self.order.append(("dropped", reason, ev.type))
    def on_transition(self, i, f, t, ev): self.order.append(("transition", ev.type))
    def on_unhandled_event(self, i, ev, ids, disposition):
        self.c[f"unhandled:{disposition}"] += 1
        self.order.append(("unhandled", disposition, ev.type))

CHAIN = {"id": "m", "initial": "a", "maxIterations": 10, "states": {
    "a": {"on": {"T": {"target": "a", "actions": ["again"]},
                 "NOPE_NOT_HANDLED": {}}}}}

def sync_chain():
    def again(i, c, e, a):
        c["n"] = c.get("n", 0) + 1; i.send("T")
    r = Rec()
    it = SyncInterpreter(create_machine(copy.deepcopy(CHAIN) | {"context": {"n": 0}},
                                        logic=MachineLogic(actions={"again": again})))
    it.use(r); it.start(); it.send("T"); it.send("UNKNOWN")
    err = type(it.last_error).__name__ if it.last_error else None
    it.stop()
    return r, err, it.context.get("n")

async def async_chain():
    async def again(i, c, e, a):
        c["n"] = c.get("n", 0) + 1; await i.send("T")
    r = Rec()
    it = Interpreter(create_machine(copy.deepcopy(CHAIN) | {"context": {"n": 0}},
                                    logic=MachineLogic(actions={"again": again})))
    it.use(r); await asyncio.wait_for(it.start(), 10)
    await it.send("T"); await asyncio.sleep(0.8); await it.send("UNKNOWN")
    await asyncio.sleep(0.2)
    err = type(it.last_error).__name__ if it.last_error else None
    n = it.context.get("n"); await it.stop()
    return r, err, n

async def main():
    sr, se, sn = sync_chain()
    ar, ae, an = await async_chain()
    print(f"  sync  chain_budget={sr.c.get('chain_budget',0)} laps={sn} trip={se} "
          f"unhandled={{k:v for k,v in sr.c.items() if 'unhandled' in k}}")
    print(f"  sync  counters={dict(sr.c)}")
    print(f"  async chain_budget={ar.c.get('chain_budget',0)} laps={an} trip={ae}")
    print(f"  async counters={dict(ar.c)}")
    print(f"  PARITY laps sync={sn} async={an} -> {'SAME' if sn == an else 'DIVERGENT'}")
    print(f"  exactly-once chain_budget: sync={sr.c.get('chain_budget',0)} "
          f"async={ar.c.get('chain_budget',0)}")
asyncio.run(main())
