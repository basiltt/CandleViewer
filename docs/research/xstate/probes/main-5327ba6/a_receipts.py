"""A — receipts under hostile reuse, defer, and overflow (main@5327ba6).

A1  same Event object sent 500x concurrently with wait=True, rollback +
    bounded inbox RAISE + defer -- do all 500 receipts resolve?
A2  wait=True on an event that is DEFERRED then replayed: does the receipt
    resolve on the defer, on the replay, or hang?
A3  wait=True on an event dropped by DROP_NEWEST -- receipt outcome
A4  wait=True on an event refused by RAISE overflow -- receipt outcome
A5  same Event object reused sequentially as a template (payload not mutated)
A6  wait=True + priority on a reused Event object
A7  receipt identity: does a deferred event's replay carry the same identity
    the receipt was keyed on?
"""

from __future__ import annotations

import asyncio
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _h  # noqa: E402

from xstate_statemachine import (  # noqa: E402
    Event,
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    QueueOverflowError,
    create_machine,
)

warnings.simplefilter("ignore", DeprecationWarning)

CFG = {
    "id": "r",
    "initial": "a",
    "context": {"n": 0},
    "actionErrorPolicy": "rollback",
    "onUnhandled": "defer",
    "states": {
        "a": {"on": {"TICK": {"actions": ["bump"]}}},
    },
}


def _bump(i, c, e, a):
    c["n"] += 1


def mk(**kw):
    return create_machine(dict(CFG, **kw), logic=MachineLogic(actions={"bump": _bump}))


# --------------------------------------------------------------- A1
@_h.probe("A1", "500 concurrent wait=True sends of ONE Event object", {"resolved": 500, "hung": 0})
async def a1():
    i = Interpreter(mk(), max_queue_size=10000, overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    ev = Event(type="TICK")
    coros = [i.send(ev, wait=True) for _ in range(500)]
    done = await asyncio.wait_for(asyncio.gather(*coros, return_exceptions=True), timeout=15)
    resolved = sum(1 for d in done if hasattr(d, "state_ids"))
    await i.stop()
    return {"resolved": resolved, "hung": 500 - resolved}


# --------------------------------------------------------------- A2
@_h.probe(
    "A2",
    "wait=True on a DEFERRED event: resolve on defer or on replay?",
    "DOCUMENT",
)
async def a2():
    cfg = {
        "id": "d",
        "initial": "a",
        "context": {},
        "onUnhandled": "defer",
        "states": {
            "a": {"on": {"GO": "b"}},
            "b": {"on": {"LATE": "c"}},
            "c": {},
        },
    }
    i = Interpreter(create_machine(cfg, logic=MachineLogic()))
    await i.start()
    # LATE is unhandled in "a" -> deferred.
    task = asyncio.ensure_future(i.send("LATE", wait=True))
    await asyncio.sleep(0.05)
    resolved_before_replay = task.done()
    deferred = i.deferred_count
    await i.send("GO")  # state change -> replays LATE
    await asyncio.sleep(0.1)
    try:
        r = await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
        outcome = {
            "resolved_at_defer_time": resolved_before_replay,
            "deferred_count_at_defer": deferred,
            "resolved": True,
            "changed": r.changed,
            "error": type(r.error).__name__ if r.error else None,
            "state": sorted(r.state_ids),
        }
    except asyncio.TimeoutError:
        task.cancel()
        outcome = {
            "resolved_at_defer_time": resolved_before_replay,
            "deferred_count_at_defer": deferred,
            "resolved": False,
            "final_state": sorted(i.current_state_ids),
        }
    await i.stop()
    return outcome


# --------------------------------------------------------------- A3
@_h.probe("A3", "wait=True on an event dropped by DROP_NEWEST", "DOCUMENT")
async def a3():
    async def slow(i, c, e, a):
        await asyncio.sleep(0.05)

    cfg = {
        "id": "s",
        "initial": "a",
        "context": {},
        "states": {"a": {"on": {"TICK": {"actions": ["slow"]}}}},
    }
    m = create_machine(cfg, logic=MachineLogic(actions={"slow": slow}))
    i = Interpreter(m, max_queue_size=2, overflow_policy=OverflowPolicy.DROP_NEWEST)
    await i.start()
    results = []
    tasks = [asyncio.ensure_future(i.send(f"TICK", wait=True)) for _ in range(12)]
    done, pending = await asyncio.wait(tasks, timeout=6.0)
    for t in tasks:
        if t.done():
            r = t.result()
            results.append(type(r.error).__name__ if r.error else "ok")
        else:
            t.cancel()
            results.append("HUNG")
    await i.stop()
    return {
        "n": len(results),
        "hung": results.count("HUNG"),
        "dropped_reported": results.count("InterpreterStoppedError"),
        "ok": results.count("ok"),
    }


# --------------------------------------------------------------- A4
@_h.probe("A4", "wait=True receipt when RAISE overflow refuses the send", "DOCUMENT")
async def a4():
    async def slow(i, c, e, a):
        await asyncio.sleep(0.05)

    cfg = {
        "id": "s",
        "initial": "a",
        "context": {},
        "states": {"a": {"on": {"TICK": {"actions": ["slow"]}}}},
    }
    m = create_machine(cfg, logic=MachineLogic(actions={"slow": slow}))
    i = Interpreter(m, max_queue_size=2, overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    raised = 0
    tasks = []
    for _ in range(12):
        try:
            tasks.append(asyncio.ensure_future(i.send("TICK", wait=True)))
            await asyncio.sleep(0)
        except QueueOverflowError:
            raised += 1
    await asyncio.sleep(0.5)
    hung = sum(1 for t in tasks if not t.done())
    errs = sorted({type(t.result().error).__name__ if t.result().error else "ok" for t in tasks if t.done()})
    for t in tasks:
        t.cancel()
    await i.stop()
    return {"raised_at_call_site": raised, "tasks": len(tasks), "hung": hung, "outcomes": errs}


# --------------------------------------------------------------- A5
@_h.probe("A5", "reused Event as a template: payload never mutated by the engine", True)
async def a5():
    i = Interpreter(mk())
    await i.start()
    ev = Event(type="TICK", payload={"k": 1})
    before = dict(ev.payload)
    for _ in range(5):
        await i.send(ev, wait=True)
    after = dict(ev.payload)
    n = i.context["n"]
    await i.stop()
    return before == after == {"k": 1} and n == 5


# --------------------------------------------------------------- A6
@_h.probe("A6", "priority + wait=True on ONE reused Event object x200", {"resolved": 200})
async def a6():
    i = Interpreter(mk())
    await i.start()
    ev = Event(type="TICK")
    res = await asyncio.wait_for(
        asyncio.gather(*[i.send(ev, wait=True, priority=True) for _ in range(200)]),
        timeout=15,
    )
    await i.stop()
    return {"resolved": sum(1 for r in res if hasattr(r, "state_ids"))}


# --------------------------------------------------------------- A7
@_h.probe("A7", "deferred event that is NEVER replayed: receipt at stop()", "DOCUMENT")
async def a7():
    cfg = {
        "id": "d2",
        "initial": "a",
        "context": {},
        "onUnhandled": "defer",
        "states": {"a": {"on": {"NOPE": {"actions": []}}}},
    }
    i = Interpreter(create_machine(cfg, logic=MachineLogic()))
    await i.start()
    t = asyncio.ensure_future(i.send("LATE", wait=True))
    await asyncio.sleep(0.05)
    pending_after_defer = not t.done()
    await i.stop()
    try:
        r = await asyncio.wait_for(t, timeout=2.0)
        out = {"pending_after_defer": pending_after_defer, "resolved_at_stop": True,
               "error": type(r.error).__name__ if r.error else None}
    except asyncio.TimeoutError:
        t.cancel()
        out = {"pending_after_defer": pending_after_defer, "resolved_at_stop": False}
    return out


if __name__ == "__main__":
    _h.main("a_receipts")
