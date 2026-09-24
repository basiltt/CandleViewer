"""LC-05 verification on xstate-statemachine 0.8.0.

Issue: `raise` was queued behind pending external events (no macrostep /
microstep distinction) -- one shared FIFO queue instead of SCXML's
internal-queue-drained-before-external-queue algorithm. 0.8.0 fix (#36) is
NOT a policy/option: both engines now hold raised events in a separate
internal queue drained to exhaustion before the next external event is
taken. This is a default-semantics fix, so there is no "opt-in" axis to
test -- only default behaviour, which must now match SCXML.

Checks (mirrors the issue's acceptance criteria and tests/test_macrostep.py):
  1. The original repro trace: ['entry', 'RAISED', 'EXTERNAL'].
  2. A raise chain A->B->C settles fully before a concurrently queued
     external event.
  3. `always` transitions interleave correctly with raised events (SCXML:
     eventless transitions taken before internal queue drains further).
  4. The runaway-raise guard (max_iterations) still trips on a self-feeding
     raise chain, without throttling normal external send() traffic.
  5. SyncInterpreter exhibits the same ordering as the async Interpreter.

Exit 0 if all pass, 1 otherwise.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine

logging.disable(logging.CRITICAL)


def _raise(event: str) -> Dict[str, Any]:
    return {"type": "raise", "params": {"event": event}}


async def check_basic_ordering() -> bool:
    trace: List[str] = []

    def mark_entry(i, c, e, a):
        trace.append("entry")

    def rec(i, c, e, a):
        trace.append(e.type)

    cfg = {
        "id": "m",
        "initial": "a",
        "context": {},
        "states": {
            "a": {"on": {"GO": "b"}},
            "b": {
                "entry": ["mark_entry", _raise("RAISED")],
                "on": {
                    "RAISED": {"actions": ["rec"]},
                    "EXTERNAL": {"actions": ["rec"]},
                },
            },
        },
    }
    logic = MachineLogic(actions={"mark_entry": mark_entry, "rec": rec})
    interp = await Interpreter(create_machine(cfg, logic=logic)).start()
    await interp.send("GO")
    await interp.send("EXTERNAL")
    await asyncio.sleep(0.3)
    await interp.stop()

    expected = ["entry", "RAISED", "EXTERNAL"]
    print("BASIC OBSERVED:", trace, " EXPECTED:", expected)
    return trace == expected


async def check_raise_chain() -> bool:
    cfg = {
        "id": "m",
        "initial": "a",
        "context": {"trace": []},
        "states": {
            "a": {
                "on": {
                    "GO": {"actions": [_raise("A")]},
                    "A": {"actions": ["la", _raise("B")]},
                    "B": {"actions": ["lb", _raise("C")]},
                    "C": {"actions": ["lc"]},
                    "EXT": {"actions": ["le"]},
                }
            }
        },
    }

    def rec(name):
        return lambda i, c, e, a: c["trace"].append(name)

    logic = MachineLogic(
        actions={"la": rec("A"), "lb": rec("B"), "lc": rec("C"), "le": rec("EXT")}
    )
    interp = await Interpreter(create_machine(cfg, logic=logic)).start()
    interp.send("GO")
    interp.send("EXT")
    for _ in range(500):
        if len(interp.context["trace"]) == 4:
            break
        await asyncio.sleep(0.002)
    out = list(interp.context["trace"])
    await interp.stop()

    expected = ["A", "B", "C", "EXT"]
    print("CHAIN OBSERVED:", out, " EXPECTED:", expected)
    return out == expected


async def check_always_interleave() -> bool:
    cfg = {
        "id": "m",
        "initial": "a",
        "context": {"trace": []},
        "states": {
            "a": {"on": {"GO": {"target": "b", "actions": [_raise("R")]}}},
            "b": {
                "always": {"target": "c", "actions": ["lb_always"]},
                "on": {"R": {"actions": ["lr_in_b"]}},
            },
            "c": {"on": {"R": {"actions": ["lr_in_c"]}}},
        },
    }

    def rec(name):
        return lambda i, c, e, a: c["trace"].append(name)

    logic = MachineLogic(
        actions={
            "lb_always": rec("always"),
            "lr_in_b": rec("R@b"),
            "lr_in_c": rec("R@c"),
        }
    )
    interp = await Interpreter(create_machine(cfg, logic=logic)).start()
    await interp.send("GO")
    for _ in range(500):
        if len(interp.context["trace"]) == 2:
            break
        await asyncio.sleep(0.002)
    trace = list(interp.context["trace"])
    state = set(interp.current_state_ids)
    await interp.stop()

    print("ALWAYS OBSERVED trace:", trace, "state:", state, " EXPECTED trace: ['always', 'R@c'], state: {'m.c'}")
    return trace == ["always", "R@c"] and state == {"m.c"}


async def check_runaway_guard() -> bool:
    cfg = {
        "id": "m",
        "initial": "a",
        "maxIterations": 50,
        "context": {"n": 0},
        "states": {"a": {"on": {"LOOP": {"actions": ["inc", _raise("LOOP")]}}}},
    }

    def inc(i, c, e, a):
        c["n"] += 1

    interp = await Interpreter(
        create_machine(cfg, logic=MachineLogic(actions={"inc": inc}))
    ).start()
    await interp.send("LOOP")
    await asyncio.sleep(0.1)
    n, status = interp.context["n"], interp.status
    await interp.stop()

    print("GUARD OBSERVED n:", n, "status:", status, " EXPECTED: status running (guard trips, does not crash), n bounded")
    return status == "running" and 0 < n < 10_000


def check_sync_ordering() -> bool:
    trace: List[str] = []

    def mark_entry(i, c, e, a):
        trace.append("entry")

    def rec(i, c, e, a):
        trace.append(e.type)

    cfg = {
        "id": "m",
        "initial": "a",
        "context": {},
        "states": {
            "a": {"on": {"GO": "b"}},
            "b": {
                "entry": ["mark_entry", _raise("RAISED")],
                "on": {
                    "RAISED": {"actions": ["rec"]},
                    "EXTERNAL": {"actions": ["rec"]},
                },
            },
        },
    }
    logic = MachineLogic(actions={"mark_entry": mark_entry, "rec": rec})
    interp = SyncInterpreter(create_machine(cfg, logic=logic))
    interp.start()
    interp.send("GO")
    interp.send("EXTERNAL")

    expected = ["entry", "RAISED", "EXTERNAL"]
    print("SYNC OBSERVED:", trace, " EXPECTED:", expected)
    return trace == expected


async def main_async() -> bool:
    r1 = await check_basic_ordering()
    r2 = await check_raise_chain()
    r3 = await check_always_interleave()
    r4 = await check_runaway_guard()
    return r1 and r2 and r3 and r4


def main() -> int:
    async_ok = asyncio.run(main_async())
    sync_ok = check_sync_ordering()
    all_ok = async_ok and sync_ok
    print(
        "RESULT:",
        "FIXED-DEFAULT (internal/external queue split, no option needed)"
        if all_ok
        else "NOT-FIXED/PARTIAL",
    )
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
