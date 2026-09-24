# -*- coding: utf-8 -*-
"""R7-02 -- an EXTERNAL `send(..., priority=True)` is charged to the chain
budget, so legitimate external traffic is silently dropped as
`reason="chain_budget"`.

`_deliver_priority` (interpreter.py:2287-2288) charges `_raise_depth`
whenever `self._processing` is true -- i.e. it decides provenance by WHEN the
event arrived, not by WHO issued it.  Every other enqueue path in the file
still asks `_issued_from_own_action()` (interpreter.py:826, :854, :1206).
The public priority lane (interpreter.py:811-812) therefore leaks onto the
chain budget: an external producer sending while the loop happens to be inside
a macrostep is treated as a self-generated chain and shed.

The run loop's own architecture note at interpreter.py:1510-1516 promises the
opposite -- that external traffic of any volume is never throttled.

Aggravating: the drop path resets `_raise_depth`/`_chain_tripped`
(interpreter.py:1596-1599), so `last_error` reads `None` afterwards and the
loss is visible ONLY through the opt-in `on_event_dropped` hook.

Control: the identical load with `priority=True` removed drops zero.

Library only, no project machinery. main @ 221ce7c (unreleased 0.8.1;
`__version__` still reports 0.8.0 -- key on the commit). Python 3.13.

Exit code 1 == external sends were dropped as `chain_budget`.
"""
import asyncio
import copy
import logging

logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

N_SENDS = 1500
MAX_ITERATIONS = 25

CFG = {
    "id": "ext",
    "maxIterations": MAX_ITERATIONS,
    "initial": "up",
    "context": {"n": 0},
    "states": {
        "up": {"on": {"TICK": {"actions": ["work"]}}},
    },
}


def make_logic(processed):
    async def work(interp, ctx, evt, ad):
        processed.append(1)
        # Any real handler that awaits keeps the loop inside a macrostep while
        # the next external event arrives.  0.5 ms is a modest DB/HTTP call.
        await asyncio.sleep(0.0005)

    return MachineLogic(actions={"work": work})


async def run(priority):
    processed = []
    dropped = []
    machine = create_machine(copy.deepcopy(CFG), logic=make_logic(processed))
    it = Interpreter(machine)

    class DropSpy(PluginBase):
        def on_event_dropped(self, interpreter, event, reason):
            dropped.append(reason)

    it.use(DropSpy())
    await it.start()

    # Strictly EXTERNAL traffic, issued on the owning loop by a caller that is
    # not inside any action -- a market-data feed, one event per 0.1 ms.  The
    # yield between sends is what lets the loop be mid-macrostep when the next
    # one lands, which is the only condition `_deliver_priority` tests.
    for _ in range(N_SENDS):
        if priority:
            it.send("TICK", priority=True)
        else:
            it.send("TICK")
        await asyncio.sleep(0.0001)
    await asyncio.sleep(2.0)
    n_proc = len(processed)
    n_drop = len(dropped)
    reasons = sorted(set(r for r in dropped if r))
    await it.stop()
    print("priority=%-5s : sent=%-5d processed=%-5d dropped=%-5d reasons=%s"
          % (priority, N_SENDS, n_proc, n_drop, reasons or "{}"))
    return n_proc, n_drop, reasons


async def main():
    print("External producer, owning loop, %d sends, maxIterations=%d.\n"
          % (N_SENDS, MAX_ITERATIONS))
    p_proc, p_drop, p_reasons = await run(True)
    c_proc, c_drop, _ = await run(False)
    print()
    if "chain_budget" in (p_reasons or []) and c_drop == 0:
        print("REPRODUCED: %d of %d external priority sends were DROPPED "
              "(reasons=%s), while the identical load WITHOUT priority=True "
              "dropped 0 and processed %d."
              % (p_drop, N_SENDS, p_reasons, c_proc))
        print("EXPECTED  : external sends are never charged to the chain "
              "budget (interpreter.py:1510-1516).")
        return 1
    print("NOT reproduced (priority processed=%d, control processed=%d)."
          % (p_proc, c_proc))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
