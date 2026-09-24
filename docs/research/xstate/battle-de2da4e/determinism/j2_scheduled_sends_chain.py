"""J2 -- scheduled_sends across restore -> persist -> restore -> start chains.

Property: a raise(delay=) heartbeat's armed delayed self-send must fire
EXACTLY ONCE and at the RIGHT remaining delay, no matter how many times the
snapshot is restored and re-persisted (without start()) before start() is
finally called. This targets #221 (parked v3 scheduled_sends re-emitted
verbatim until start() consumes them) across a longer restore chain than the
original repro used.

>= 300 property cases: (delay, n_restore_cycles, tick_before_restore) triples.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

FIRE_COUNT = {"n": 0}


def _cfg(delay):
    arm = {"type": "raise", "params": {"event": "BEAT", "delay": delay}}
    return {
        "id": "hb",
        "initial": "beat",
        "states": {
            "beat": {
                "entry": [arm],
                "on": {"BEAT": {"actions": ["fire"]}},
            }
        },
    }


def fire(i, c, e, a):
    c["fires"] = c.get("fires", 0) + 1


async def run_case(delay, n_cycles, pre_tick):
    machine = create_machine(_cfg(delay), logic=MachineLogic(actions={"fire": fire}))
    clock = SimulatedClock()
    interp = Interpreter(machine, clock=clock)
    await interp.start()
    if pre_tick:
        await clock.increment(pre_tick)
    snap = interp.get_persisted_snapshot()
    await interp.stop()

    # chain of restore -> persist (no start) cycles
    cur_snap = snap
    for _ in range(n_cycles):
        machine2 = create_machine(_cfg(delay), logic=MachineLogic(actions={"fire": fire}))
        interp2 = Interpreter.from_snapshot(json.dumps(cur_snap), machine2)
        cur_snap = interp2.get_persisted_snapshot()
        # scheduled_sends must survive verbatim (parked, unconsumed)
        assert cur_snap.get("scheduled_sends"), (
            f"lost scheduled_sends after cycle (delay={delay}, n_cycles={n_cycles})"
        )

    # finally restore + start
    machine3 = create_machine(_cfg(delay), logic=MachineLogic(actions={"fire": fire}))
    clock3 = SimulatedClock()
    interp3 = Interpreter.from_snapshot(json.dumps(cur_snap), machine3, clock=clock3)
    await interp3.start()
    remaining = max(delay - pre_tick, 0)
    # advance a bit short of remaining -> should not have fired yet (if remaining>0)
    if remaining > 1:
        await clock3.increment(remaining - 1)
        n_before = interp3.context.get("fires", 0)
    else:
        n_before = interp3.context.get("fires", 0)
    await clock3.increment(2)  # cross the deadline
    import asyncio
    for _ in range(3):
        await asyncio.sleep(0)
    n_after = interp3.context.get("fires", 0)
    await interp3.stop()
    fired_exactly_once = (n_after - n_before) == 1
    return fired_exactly_once, n_before, n_after


async def main():
    random.seed(1234)
    cases = []
    for _ in range(320):
        delay = random.choice([5, 10, 20, 50, 100])
        n_cycles = random.choice([0, 1, 2, 3, 5])
        pre_tick = random.randint(0, delay - 1) if delay > 1 else 0
        cases.append((delay, n_cycles, pre_tick))

    fails = []
    for (delay, n_cycles, pre_tick) in cases:
        try:
            ok, nb, na = await run_case(delay, n_cycles, pre_tick)
        except Exception as ex:  # noqa: BLE001
            fails.append((delay, n_cycles, pre_tick, f"EXC:{ex}"))
            continue
        if not ok:
            fails.append((delay, n_cycles, pre_tick, f"nb={nb} na={na}"))

    print(f"cases run: {len(cases)}")
    print(f"failures : {len(fails)}")
    for f in fails[:10]:
        print("  FAIL", f)
    print("VERDICT", "PASS" if not fails else "FAIL")
    with open(os.path.join(os.path.dirname(__file__), "out", "j2_scheduled_sends_chain.json"), "w") as fh:
        json.dump({"cases": len(cases), "failures": fails[:50]}, fh, indent=2)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
