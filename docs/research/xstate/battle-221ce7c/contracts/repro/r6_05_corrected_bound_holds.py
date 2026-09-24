# -*- coding: utf-8 -*-
"""Corrected-usage variant of R6-05: does the BOUND get bypassed, or only the
call-site signal, while the loop is busy?  Reads the returned future, which the
send_threadsafe docstring names as the carrier for loop-side refusals."""
import asyncio, threading, time
from xstate_statemachine import (create_machine, MachineLogic, Interpreter,
                                 OverflowPolicy, QueueOverflowError)

CFG = {"id": "q", "initial": "a", "context": {},
       "states": {"a": {"on": {"PING": {"actions": ["bump"]}}}}}
processed, drops, depths = [], [], []

class DropWatch:
    def on_event_dropped(self, interp, event, reason):
        drops.append(reason)

async def bump(i, c, e, a):
    processed.append(1)

async def main():
    m = create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))
    it = Interpreter(m, max_queue_size=3, overflow_policy=OverflowPolicy.RAISE)
    it.use(DropWatch())
    await it.start()
    res, futs = [], []
    def producer():
        for _ in range(500):
            try:
                futs.append(it.send_threadsafe("PING", internal=False))
                res.append("accepted")
            except QueueOverflowError:
                res.append("raised-at-call-site")
    t = threading.Thread(target=producer); t.start()
    time.sleep(0.8)                      # loop blocked
    depths.append(it._event_queue.qsize())
    t.join(5)
    for _ in range(25):
        await asyncio.sleep(0.05)
        depths.append(it._event_queue.qsize())
    fut_raised = fut_ok = fut_other = 0
    for f in futs:
        try:
            f.result(timeout=2); fut_ok += 1
        except QueueOverflowError:
            fut_raised += 1
        except Exception as e:
            fut_other += 1; print("other:", type(e).__name__, e)
    print("call-site accepted     : %d" % res.count("accepted"))
    print("call-site raised       : %d" % res.count("raised-at-call-site"))
    print("FUTURE raised QOE      : %d   <-- refused on the loop" % fut_raised)
    print("FUTURE ok (enqueued)   : %d" % fut_ok)
    print("FUTURE other exc       : %d" % fut_other)
    print("max observed qsize     : %d   (bound = 3)" % max(depths))
    print("actually ran           : %d" % len(processed))
    print("on_event_dropped       : %d" % len(drops))
    await it.stop()

asyncio.run(main())
