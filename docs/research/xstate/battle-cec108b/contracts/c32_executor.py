# -*- coding: utf-8 -*-
"""CV-C32 re-test on cec108b (#149): are plain-`def` services still required
to be `async def`, or does the new service_executor make the rule unnecessary?

Checks three things on the *async* engine with a plain-def service:
  1. does it run at all;
  2. does it block the event loop for its duration (the #149 complaint);
  3. does its completion still land after the entering macrostep (#116 order).
"""
from __future__ import annotations
import asyncio, json, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

CFG = {
    "id": "c32", "initial": "idle",
    "context": {"trace": []},
    "states": {
        "idle": {"on": {"GO": "working"}},
        "working": {
            "entry": ["mark_entry"],
            "invoke": {"id": "w", "src": "slow",
                       "onDone": {"target": "done", "actions": ["mark_done"]},
                       "onError": {"target": "failed", "actions": ["mark_err"]}},
            "on": {"PING": {"actions": ["mark_ping"]}},
        },
        "done": {}, "failed": {},
    },
}


def mk_logic(svc):
    def act(n):
        def f(i, ctx, e, a):
            ctx["trace"].append(n)
        f.__name__ = n
        return f
    return MachineLogic(
        actions={n: act(n) for n in ("mark_entry", "mark_done", "mark_ping", "mark_err")},
        services={"slow": svc}, strict=True)


async def probe(svc, label, executor=None, dur=0.35):
    m = create_machine(json.loads(json.dumps(CFG)), logic=mk_logic(svc))
    kw = {}
    if executor is not None:
        kw["service_executor"] = executor
    i = Interpreter(m, clock=SimulatedClock(), **kw)
    await i.start()
    # loop-liveness sampler: counts turns of the event loop during the service
    ticks = {"n": 0}

    async def sampler():
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < dur + 0.15:
            ticks["n"] += 1
            await asyncio.sleep(0.01)

    s = asyncio.create_task(sampler())
    await i.send("GO")
    await asyncio.sleep(0.05)
    await s
    await asyncio.sleep(0.2)
    print("%-22s ids=%-22s trace=%-42s loop_turns=%3d" %
          (label, sorted(i.current_state_ids), i.context["trace"], ticks["n"]))
    await i.stop()
    return sorted(i.current_state_ids), list(i.context["trace"]), ticks["n"]


def plain_def(interp, ctx, event):
    time.sleep(0.35)
    return {"ok": True}


def plain_raises(interp, ctx, event):
    time.sleep(0.05)
    raise RuntimeError("plain boom")


async def async_def(interp, ctx, event):
    await asyncio.sleep(0.35)
    return {"ok": True}


async def main():
    print("expected: ~50 loop turns if the loop keeps turning, ~5 if blocked")
    await probe(async_def, "async def (CV-C32)")
    await probe(plain_def, "plain def (default)")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as ex:
        await probe(plain_def, "plain def (own executor)", executor=ex)
    await probe(plain_raises, "plain def raising", dur=0.05)

asyncio.run(main())
