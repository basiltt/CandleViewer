"""C — SyncInterpreter per-chain budget (#77 / N-3), hostile shapes.

C1  1000-deep LEGITIMATE chain (each raise triggers exactly one more,
    terminating) -- delivered in full, or cut at max_iterations?
C2  999-deep chain (just under) -- control.
C3  3000 independent one-deep raises in ONE send_events batch -- all through?
C4  a genuine self-feeding infinite loop is still broken, and the caller's
    own queued events still processed.
C5  interleave EXTERNAL events during a chain: a batch of [CHAIN, T, T, T...]
    -- are the trailing externals delivered after the chain trips?
C6  raise-chain depth exactly at the limit boundary (1000 vs 1001).
C7  engine parity: same 1000-deep chain on the ASYNC engine.
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


def _chain_cfg(depth: int, machine_id: str = "chain") -> dict:
    """STEP re-raises STEP until ctx.n == depth, then stops. Terminating."""
    return {
        "id": machine_id,
        "initial": "run",
        "context": {"n": 0, "depth": depth},
        "states": {
            "run": {
                "on": {
                    "STEP": {"actions": ["step"]},
                    "T": {"actions": ["ext"]},
                }
            }
        },
    }


def _logic():
    def step(i, c, e, a):
        c["n"] += 1
        if c["n"] < c["depth"]:
            i.send("STEP")

    def ext(i, c, e, a):
        c.setdefault("ext", 0)
        c["ext"] += 1

    return MachineLogic(actions={"step": step, "ext": ext})


# --------------------------------------------------------------- C1
@_h.probe("C1", "sync: 1000-deep legitimate terminating chain", {"n": 1000})
def c1():
    i = SyncInterpreter(create_machine(_chain_cfg(1000), logic=_logic())).start()
    i.send("STEP")
    out = {"n": i.context["n"]}
    i.stop()
    return out


# --------------------------------------------------------------- C2
@_h.probe("C2", "sync: 999-deep chain (control)", {"n": 999})
def c2():
    i = SyncInterpreter(create_machine(_chain_cfg(999), logic=_logic())).start()
    i.send("STEP")
    out = {"n": i.context["n"]}
    i.stop()
    return out


# --------------------------------------------------------------- C2b
@_h.probe("C2b", "sync: 1500-deep chain", {"n": 1500})
def c2b():
    i = SyncInterpreter(create_machine(_chain_cfg(1500), logic=_logic())).start()
    i.send("STEP")
    out = {"n": i.context["n"]}
    i.stop()
    return out


# --------------------------------------------------------------- C3
@_h.probe("C3", "sync: 3000 independent one-deep raises in one batch", {"n": 3000})
def c3():
    i = SyncInterpreter(create_machine(_chain_cfg(1), logic=_logic())).start()
    i.context["depth"] = 1  # each STEP raises nothing further
    i.send_events(["STEP"] * 3000)
    out = {"n": i.context["n"]}
    i.stop()
    return out


# --------------------------------------------------------------- C4
@_h.probe(
    "C4",
    "sync: genuine infinite self-feed is broken; caller's queued T's survive",
    {"looped": True, "ext": 50},
)
def c4():
    cfg = {
        "id": "loop",
        "initial": "run",
        "context": {"n": 0, "ext": 0},
        "states": {
            "run": {
                "on": {
                    "LOOP": {"actions": ["spin"]},
                    "T": {"actions": ["ext"]},
                }
            }
        },
    }

    def spin(i, c, e, a):
        c["n"] += 1
        i.send("LOOP")  # never terminates

    def ext(i, c, e, a):
        c["ext"] += 1

    i = SyncInterpreter(
        create_machine(cfg, logic=MachineLogic(actions={"spin": spin, "ext": ext}))
    ).start()
    i.send_events(["LOOP"] + ["T"] * 50)
    out = {"looped": i.context["n"] > 0, "ext": i.context["ext"]}
    i.stop()
    return out


# --------------------------------------------------------------- C5
@_h.probe(
    "C5",
    "sync: externals interleaved AFTER a 2000-deep chain in one batch",
    {"n": 2000, "ext": 100},
)
def c5():
    i = SyncInterpreter(create_machine(_chain_cfg(2000), logic=_logic())).start()
    i.context["ext"] = 0
    i.send_events(["STEP"] + ["T"] * 100)
    out = {"n": i.context["n"], "ext": i.context["ext"]}
    i.stop()
    return out


# --------------------------------------------------------------- C6
@_h.probe("C6", "sync: 1001-deep chain (limit+1)", {"n": 1001})
def c6():
    i = SyncInterpreter(create_machine(_chain_cfg(1001), logic=_logic())).start()
    i.send("STEP")
    out = {"n": i.context["n"]}
    i.stop()
    return out


# --------------------------------------------------------------- C7
@_h.probe("C7", "async engine: same 1000-deep legitimate chain", {"n": 1000})
async def c7():
    cfg = _chain_cfg(1000, "achain")
    i = Interpreter(create_machine(cfg, logic=_logic()))
    await i.start()
    await i.send("STEP")
    for _ in range(200):
        await asyncio.sleep(0.01)
        if i.context["n"] >= 1000:
            break
    out = {"n": i.context["n"]}
    await i.stop()
    return out


# --------------------------------------------------------------- C8
@_h.probe("C8", "async engine: 1500-deep legitimate chain", {"n": 1500})
async def c8():
    cfg = _chain_cfg(1500, "achain2")
    i = Interpreter(create_machine(cfg, logic=_logic()))
    await i.start()
    await i.send("STEP")
    for _ in range(300):
        await asyncio.sleep(0.01)
        if i.context["n"] >= 1500:
            break
    out = {"n": i.context["n"]}
    await i.stop()
    return out


if __name__ == "__main__":
    _h.main("c_sync_chain_budget")
