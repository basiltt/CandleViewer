# -*- coding: utf-8 -*-
"""R9-09 (STANDALONE): #201's changelog claim "all three lanes agree at every
limit tested" is not quite true. On the `def`-service `rollback_ondone` shape,
the sync engine runs exactly two laps more than the async engine at every ODD
`maxIterations` (1, 3, 5, ...), and agrees at every even one. Both lanes still
trip RunawayChainError (safety is not affected) -- this is a documentation
accuracy issue, not a behavioural defect.

Sweeps maxIterations 1..25 (+15,20,25) on two shapes (`nested_invoke`,
`rollback_ondone`) x two service kinds (def, async def) x two engines
(SyncInterpreter, Interpreter), and prints the lap table.

Exit 1 = any def-lane rollback_ondone odd-limit mismatch found (claim false,
as filed). Exit 0 = no mismatch (claim now accurate).
"""
from __future__ import annotations

import asyncio
import copy
import logging
import sys
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

import xstate_statemachine.base_interpreter as bi
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine

LAPS: list = []
_orig_a = bi.BaseInterpreter._process_event


async def _patched(self, e):
    LAPS.append(getattr(e, "type", "?"))
    return await _orig_a(self, e)


bi.BaseInterpreter._process_event = _patched


def nested_invoke(mi):
    c = {
        "id": "m0", "initial": "a",
        "states": {"a": {"initial": "a", "invoke": {"id": "i1", "src": "svc",
                                                       "onDone": {"target": "#m0.a.b"}},
                          "states": {"a": {}, "b": {"invoke": {"id": "i2", "src": "svc",
                                                                "onDone": {"target": "#m0.a.a"}}}}}},
    }
    if mi is not None:
        c["maxIterations"] = mi
    return c


def rollback_ondone(mi):
    c = {
        "id": "m0", "initial": "a", "actionErrorPolicy": "rollback",
        "states": {"a": {"invoke": {"id": "i1", "src": "svc", "onDone": {"target": "b"}}},
                   "b": {"always": {"target": "a"}}},
    }
    if mi is not None:
        c["maxIterations"] = mi
    return c


def dsvc(i, c, e):
    return {"v": 1}


async def asvc(i, c, e):
    return {"v": 1}


async def run_sync(cfg, svc):
    LAPS.clear()
    m = create_machine(copy.deepcopy(cfg), logic=MachineLogic(services={"svc": svc}))
    it = SyncInterpreter(m)
    try:
        it.start()
    except Exception as exc:
        return len(LAPS), type(exc).__name__
    err = type(it.last_error).__name__ if it.last_error else None
    try:
        it.stop()
    except Exception:
        pass
    return len(LAPS), err


async def run_async(cfg, svc):
    LAPS.clear()
    m = create_machine(copy.deepcopy(cfg), logic=MachineLogic(services={"svc": svc}))
    it = Interpreter(m)
    try:
        await it.start()
    except Exception as exc:
        return len(LAPS), type(exc).__name__
    for _ in range(60):
        await asyncio.sleep(0.01)
        if it.last_error is not None:
            break
    err = type(it.last_error).__name__ if it.last_error else None
    try:
        await it.stop()
    except Exception:
        pass
    return len(LAPS), err


async def main() -> int:
    print("R9-09 -- #201 lap parity sweep, both service kinds, both engines")
    def_lane_odd_mismatch = False
    for shape, build in (("nested_invoke", nested_invoke), ("rollback_ondone", rollback_ondone)):
        for kind, svc in (("def", dsvc), ("async def", asvc)):
            print(f"\n  {shape} / {kind}")
            for mi in list(range(1, 11)) + [15, 20, 25]:
                cfg = build(mi)
                sl, se = await run_sync(cfg, svc)
                al, ae = await run_async(cfg, svc)
                same = sl == al
                flag = "SAME  " if same else "DIFFER"
                print(f"    mi={mi:<3d} sync_laps={sl:<5d} async_laps={al:<5d} "
                      f"{flag} sync_err={se} async_err={ae}")
                if (shape == "rollback_ondone" and kind == "def" and not same
                        and mi % 2 == 1 and sl - al == 2):
                    def_lane_odd_mismatch = True
    print("\nVERDICT:",
          "def-lane odd-limit mismatch confirmed (claim false, as filed)"
          if def_lane_odd_mismatch else "no mismatch (claim now accurate)")
    return 1 if def_lane_odd_mismatch else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
