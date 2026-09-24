"""C9..C13 — chain budget with the `raise` BUILT-IN (not action-side send()).

C_1 isolates whether the 1001-cut in `c_sync_chain_budget.py` C2b/C5 is
specific to an action calling `i.send()` on itself, or applies equally to
the SCXML `raise` built-in, and whether the async engine agrees.

A guarded terminating chain: STEP raises STEP while n < depth.
"""

from __future__ import annotations

import asyncio
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _h  # noqa: E402

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

warnings.simplefilter("ignore", DeprecationWarning)


def cfg(depth: int, mid: str) -> dict:
    return {
        "id": mid,
        "initial": "run",
        "context": {"n": 0, "depth": depth},
        "states": {
            "run": {
                "on": {
                    "STEP": {
                        "actions": [
                            "bump",
                            {
                                "type": "raise",
                                "params": {"event": "STEP"},
                                "cond": "more",
                            },
                        ]
                    }
                }
            }
        },
    }


def logic():
    def bump(i, c, e, a):
        c["n"] += 1

    def more(c, e):
        return c["n"] < c["depth"]

    return MachineLogic(actions={"bump": bump}, guards={"more": more})


def _sync(depth):
    i = SyncInterpreter(create_machine(cfg(depth, f"s{depth}"), logic=logic())).start()
    i.send("STEP")
    n = i.context["n"]
    i.stop()
    return n


async def _async(depth):
    i = Interpreter(create_machine(cfg(depth, f"a{depth}"), logic=logic()))
    await i.start()
    await i.send("STEP")
    for _ in range(600):
        await asyncio.sleep(0.005)
        if i.context["n"] >= depth:
            break
    n = i.context["n"]
    await i.stop()
    return n


@_h.probe("C9", "sync + raise built-in: 1500-deep guarded chain", {"n": 1500})
def c9():
    return {"n": _sync(1500)}


@_h.probe("C10", "async + raise built-in: 1500-deep guarded chain", {"n": 1500})
async def c10():
    return {"n": await _async(1500)}


@_h.probe("C11", "sync + raise built-in: 3000-deep guarded chain", {"n": 3000})
def c11():
    return {"n": _sync(3000)}


@_h.probe("C12", "async + raise built-in: 3000-deep guarded chain", {"n": 3000})
async def c12():
    return {"n": await _async(3000)}


@_h.probe(
    "C13",
    "async: action-side i.send() self-chain is NOT budgeted at all (10000 deep)",
    {"n": 10000},
)
async def c13():
    c = {
        "id": "asend",
        "initial": "run",
        "context": {"n": 0, "depth": 10000},
        "states": {"run": {"on": {"STEP": {"actions": ["step"]}}}},
    }

    def step(i, ctx, e, a):
        ctx["n"] += 1
        if ctx["n"] < ctx["depth"]:
            i.send("STEP")

    i = Interpreter(create_machine(c, logic=MachineLogic(actions={"step": step})))
    await i.start()
    await i.send("STEP")
    for _ in range(2000):
        await asyncio.sleep(0.002)
        if i.context["n"] >= 10000:
            break
    n = i.context["n"]
    await i.stop()
    return {"n": n}


if __name__ == "__main__":
    _h.main("c2_raise_builtin_chain")
