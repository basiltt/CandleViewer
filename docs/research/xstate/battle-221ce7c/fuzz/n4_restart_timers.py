"""N4 -- #128 restart_timers=True: does the re-armed `after` deadline actually
fire on SyncInterpreter, as it does on Interpreter?

Both engines, identical machine and SimulatedClock discipline.
"""
from __future__ import annotations
import asyncio, copy, json, logging, warnings
warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (Interpreter, SyncInterpreter, SimulatedClock,
                                 create_machine, MachineLogic)

CFG = {"id": "m", "initial": "a", "states": {"a": {"after": {"50": "b"}}, "b": {}}}


def L():
    return MachineLogic()


def sync_case():
    clk = SimulatedClock()
    i = SyncInterpreter(create_machine(copy.deepcopy(CFG), logic=L()), clock=clk)
    i.start()
    snap = i.get_persisted_snapshot()
    i.stop()
    out = {}
    for label, kw in (("no-restart", {}), ("restart_timers=True", {"restart_timers": True})):
        c = SimulatedClock()
        r = SyncInterpreter.from_snapshot(
            json.dumps(snap), create_machine(copy.deepcopy(CFG), logic=L()),
            clock=c, **kw)
        r.start()
        dormant = r.has_dormant_timers
        c.increment(100)          # 100 ms >> the 50 ms deadline
        r.tick()
        r.tick()                  # a second tick in case one drains one lane
        out[label] = (dormant, sorted(r.current_state_ids), c.pending)
    # control: a FRESH sync machine on a SimulatedClock -- does `after` fire at all?
    c = SimulatedClock()
    f = SyncInterpreter(create_machine(copy.deepcopy(CFG), logic=L()), clock=c)
    f.start()
    c.increment(100)
    f.tick()
    out["control-fresh-sync"] = (f.has_dormant_timers, sorted(f.current_state_ids),
                                 c.pending)
    return out


def async_case():
    async def main():
        clk = SimulatedClock()
        i = await Interpreter(create_machine(copy.deepcopy(CFG), logic=L()),
                              clock=clk).start()
        snap = i.get_snapshot()
        await i.stop()
        out = {}
        for label, kw in (("no-restart", {}),
                          ("restart_timers=True", {"restart_timers": True})):
            c = SimulatedClock()
            r = Interpreter.from_snapshot(
                snap, create_machine(copy.deepcopy(CFG), logic=L()), clock=c, **kw)
            await r.start()
            dormant = r.has_dormant_timers
            await c.increment(100)
            await asyncio.sleep(0.02)
            out[label] = (dormant, r.value)
            await r.stop()
        return out
    return asyncio.run(asyncio.wait_for(main(), 30))


if __name__ == "__main__":
    print("SYNC :")
    for k, v in sync_case().items():
        print(f"   {k:22} has_dormant_timers={v[0]} state={v[1]} clock_pending={v[2]}")
    print("ASYNC:")
    for k, v in async_case().items():
        print(f"   {k:22} has_dormant_timers={v[0]} value={v[1]}")
