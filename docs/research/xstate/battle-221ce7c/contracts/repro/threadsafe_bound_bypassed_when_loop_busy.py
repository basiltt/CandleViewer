# -*- coding: utf-8 -*-
"""Standalone repro: `send_threadsafe` under OverflowPolicy.RAISE enforces the
inbox bound against a STALE queue depth, so the bound is bypassed exactly when
it is needed -- while the event loop is busy.

cec108b (unreleased 0.8.1). Library only.

#157 moved the backpressure check to the calling thread:

    if not self_issued and policy is RAISE and self._inbox_is_full():
        raise QueueOverflowError(...)          # interpreter.py ~1118

`_inbox_is_full()` reads `self._event_queue.qsize()`. The actual enqueue happens
later, inside `_deliver()`, via `asyncio.run_coroutine_threadsafe`. While the
loop thread is busy (a slow action, a blocking service on the executor, a
`time.sleep` in a callback) no `_deliver` runs, so `qsize()` stays at its old
value -- typically 0 -- and EVERY call passes the check no matter how many are
already in flight.

Run below: 500 cross-thread sends into a 3-slot RAISE inbox while the loop is
blocked for 0.8s.
  expected: a handful accepted, the rest QueueOverflowError on the caller
  actual:   all 500 accepted, 0 raised, only ~3 ever processed, and
            `on_event_dropped` never fires -- the rest vanish silently.

The same script with the loop NOT blocked raises correctly (2974/3000), which is
why the pinned test passes: it only exercises the idle-loop case.
"""
import asyncio, threading, time
from xstate_statemachine import (create_machine, MachineLogic, Interpreter,
                                 OverflowPolicy, QueueOverflowError)

CFG = {"id": "q", "initial": "a", "context": {},
       "states": {"a": {"on": {"PING": {"actions": ["bump"]}}}}}

processed, drops = [], []


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

    res = []

    def producer():
        for i in range(500):
            try:
                it.send_threadsafe("PING", internal=False)
                res.append("accepted")
            except QueueOverflowError:
                res.append("raised")

    t = threading.Thread(target=producer)
    t.start()
    time.sleep(0.8)          # <-- loop thread blocked; nothing drains
    t.join(5)
    for _ in range(25):
        await asyncio.sleep(0.2)

    print("accepted        : %d" % res.count("accepted"))
    print("QueueOverflow   : %d   <-- expected ~497" % res.count("raised"))
    print("actually ran    : %d" % len(processed))
    print("on_event_dropped: %d   <-- silent loss" % len(drops))
    await it.stop()


asyncio.run(main())
