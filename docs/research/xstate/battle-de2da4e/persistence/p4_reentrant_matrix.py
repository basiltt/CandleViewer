# -*- coding: utf-8 -*-
"""P4 (#219) -- the ReentrantWaitError matrix.  STANDALONE.

Cells (both engines where applicable, both service kinds):
 A  entry action awaits `i.send(..., wait=True)` on its OWN interpreter
    during start()            -> must raise ReentrantWaitError, start()
                                 must RETURN (the #219 hang shape).
 B  a normal (post-start) action does the same             -> refused.
 C  an `after`-fired handler action does the same          -> refused.
 D  the DEFERRED pattern: action does
    `asyncio.ensure_future(i.send(..., wait=True))` and does NOT await
    it in-step                -> allowed; receipt resolves later.
 E  child -> parent `wait=True` send (different interpreter) -> ALLOWED.
 F  parent -> child `wait=True` send                         -> ALLOWED.
 G  sync engine: same self-send refusal for parity.
 H  100 CONCURRENT actions using the ensure_future pattern: all receipts
    resolve, no hang, no ReentrantWaitError.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from xstate_statemachine import (Interpreter, MachineLogic, SyncInterpreter,
                                 create_machine)
from xstate_statemachine.exceptions import ReentrantWaitError

KIND = os.environ.get("XS_SVC", "async")
TMO = float(os.environ.get("XS_TMO", "5"))


def mach(cfg, actions, services=None):
    return create_machine(json.loads(json.dumps(cfg)),
                          logic=MachineLogic(actions=actions,
                                             services=services or {}))


def label(exc):
    return type(exc).__name__ if exc else None


CFG_A = {"id": "ra", "initial": "a", "context": {},
         "states": {"a": {"entry": ["boom"], "on": {"X": "b"}}, "b": {}}}


async def cell_a():
    box = {}

    async def boom(i, c, e, a):
        try:
            await i.send("X", wait=True)
            box["r"] = "NO-RAISE"
        except Exception as ex:
            box["r"] = label(ex)

    i = Interpreter(mach(CFG_A, {"boom": boom}))
    try:
        await asyncio.wait_for(i.start(), TMO)
        box["start"] = "returned"
    except asyncio.TimeoutError:
        box["start"] = "HANG"
    try:
        await asyncio.wait_for(i.stop(), 2)
    except Exception:
        pass
    return box


CFG_B = {"id": "rb", "initial": "a", "context": {},
         "states": {"a": {"on": {"GO": {"actions": ["boom"]}, "X": "b"}},
                    "b": {}}}


async def cell_b():
    box = {}

    async def boom(i, c, e, a):
        try:
            await i.send("X", wait=True)
            box["r"] = "NO-RAISE"
        except Exception as ex:
            box["r"] = label(ex)

    i = Interpreter(mach(CFG_B, {"boom": boom}))
    await i.start()
    try:
        await asyncio.wait_for(i.send("GO"), TMO)
        for _ in range(200):
            if "r" in box:
                break
            await asyncio.sleep(0.01)
        box["send"] = "returned"
    except asyncio.TimeoutError:
        box["send"] = "HANG"
    await asyncio.wait_for(i.stop(), 2)
    return box


CFG_C = {"id": "rc", "initial": "a", "context": {},
         "states": {"a": {"after": {"20": {"actions": ["boom"],
                                           "target": "a",
                                           "reenter": False}}},
                    "b": {}},
         "maxIterations": 50}


async def cell_c():
    box = {}
    done = asyncio.Event()

    async def boom(i, c, e, a):
        try:
            await i.send("X", wait=True)
            box["r"] = "NO-RAISE"
        except Exception as ex:
            box["r"] = label(ex)
        done.set()

    i = Interpreter(mach(CFG_C, {"boom": boom}))
    await i.start()
    try:
        await asyncio.wait_for(done.wait(), TMO)
        box["fired"] = True
    except asyncio.TimeoutError:
        box["fired"] = "HANG"
    await asyncio.wait_for(i.stop(), 2)
    return box


async def cell_d():
    """Deferred receipt: hand it out, await it AFTER the step."""
    box = {}
    fut = {}

    async def boom(i, c, e, a):
        fut["f"] = asyncio.ensure_future(i.send("X", wait=True))

    i = Interpreter(mach(CFG_B, {"boom": boom}))
    await i.start()
    await asyncio.wait_for(i.send("GO"), TMO)
    for _ in range(200):
        if "f" in fut:
            break
        await asyncio.sleep(0.01)
    try:
        await asyncio.wait_for(fut["f"], TMO)
        box["receipt"] = "resolved"
    except asyncio.TimeoutError:
        box["receipt"] = "HANG"
    except Exception as ex:
        box["receipt"] = label(ex)
    box["state"] = sorted(s.id for s in i._active_state_nodes)
    await asyncio.wait_for(i.stop(), 2)
    return box


PARENT = {"id": "par", "initial": "a", "context": {},
          "states": {"a": {"on": {"FROMCHILD": {"actions": ["note"]},
                                  "P2C": {"actions": ["p2c"]}}}}}
CHILD = {"id": "chi", "initial": "a", "context": {},
         "states": {"a": {"on": {"GO": {"actions": ["up"]},
                                 "FROMPARENT": {"actions": ["note"]}}}}}


async def cell_ef():
    box = {}
    notes = []
    holder = {}

    def note(i, c, e, a):
        notes.append((i.id, e.type))

    async def up(i, c, e, a):
        try:
            await asyncio.wait_for(
                holder["parent"].send("FROMCHILD", wait=True), TMO)
            box["child_to_parent"] = "OK"
        except asyncio.TimeoutError:
            box["child_to_parent"] = "HANG"
        except Exception as ex:
            box["child_to_parent"] = label(ex)

    async def p2c(i, c, e, a):
        try:
            await asyncio.wait_for(
                holder["child"].send("FROMPARENT", wait=True), TMO)
            box["parent_to_child"] = "OK"
        except asyncio.TimeoutError:
            box["parent_to_child"] = "HANG"
        except Exception as ex:
            box["parent_to_child"] = label(ex)

    p = Interpreter(mach(PARENT, {"note": note, "p2c": p2c}))
    c = Interpreter(mach(CHILD, {"note": note, "up": up}))
    holder["parent"], holder["child"] = p, c
    await p.start()
    await c.start()
    try:
        await asyncio.wait_for(c.send("GO"), TMO + 1)
    except asyncio.TimeoutError:
        box["child_to_parent"] = "HANG(outer)"
    for _ in range(200):
        if "child_to_parent" in box:
            break
        await asyncio.sleep(0.01)
    try:
        await asyncio.wait_for(p.send("P2C"), TMO + 1)
    except asyncio.TimeoutError:
        box["parent_to_child"] = "HANG(outer)"
    for _ in range(300):
        if "parent_to_child" in box:
            break
        await asyncio.sleep(0.01)
    box["notes"] = notes
    await p.stop()
    await c.stop()
    return box


def cell_g():
    box = {}

    def boom(i, c, e, a):
        try:
            i.send("X", wait=True)
            box["r"] = "NO-RAISE"
        except Exception as ex:
            box["r"] = label(ex)

    i = SyncInterpreter(mach(CFG_A, {"boom": boom}))
    i.start()
    box["start"] = "returned"
    i.stop()
    return box


CFG_H = {"id": "rh", "initial": "a", "context": {"x": 0},
         "states": {"a": {"on": {"GO": {"actions": ["boom"]},
                                 "X": {"actions": ["tick"]}}}}}


async def cell_h(n=100):
    """100 concurrent actions using the deferred receipt pattern."""
    futs = []

    def tick(i, c, e, a):
        c["x"] += 1

    async def boom(i, c, e, a):
        futs.append(asyncio.ensure_future(i.send("X", wait=True)))

    i = Interpreter(mach(CFG_H, {"boom": boom, "tick": tick}))
    await i.start()
    try:
        await asyncio.wait_for(
            asyncio.gather(*[i.send("GO") for _ in range(n)]), TMO * 2)
    except asyncio.TimeoutError:
        return {"n": n, "outer": "HANG"}
    for _ in range(400):
        if len(futs) >= n:
            break
        await asyncio.sleep(0.01)
    try:
        await asyncio.wait_for(asyncio.gather(*futs, return_exceptions=True),
                               TMO * 2)
        res = [label(f.exception()) if f.exception() else "ok" for f in futs]
    except asyncio.TimeoutError:
        res = ["HANG"]
    await asyncio.wait_for(i.stop(), 3)
    from collections import Counter
    return {"n": n, "receipts": len(futs), "outcomes": dict(Counter(res))}


async def main():
    out = {"kind": KIND}
    out["A_entry_self"] = await cell_a()
    out["B_action_self"] = await cell_b()
    out["C_after_handler_self"] = await cell_c()
    out["D_deferred_receipt"] = await cell_d()
    out["EF_cross_interpreter"] = await cell_ef()
    out["G_sync_self"] = cell_g()
    out["H_100_concurrent_deferred"] = await cell_h()
    R = "ReentrantWaitError"
    ok = (out["A_entry_self"].get("r") == R
          and out["A_entry_self"].get("start") == "returned"
          and out["B_action_self"].get("r") == R
          and out["C_after_handler_self"].get("r") == R
          and out["D_deferred_receipt"].get("receipt") == "resolved"
          and out["EF_cross_interpreter"].get("child_to_parent") == "OK"
          and out["EF_cross_interpreter"].get("parent_to_child") == "OK"
          and out["G_sync_self"].get("r") == R
          and out["H_100_concurrent_deferred"].get("outcomes", {}).get(
              "ok") == 100)
    out["VERDICT"] = "PASS" if ok else "FAIL"
    print(json.dumps(out, indent=1, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
