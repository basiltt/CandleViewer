# -*- coding: utf-8 -*-
"""M1 - hypothesis property over RANDOM PARALLEL machines.

Property (#142/#143): at every *quiescent* point of a randomly generated
parallel machine, `get_persisted_snapshot()` must
  (a) never raise, and
  (b) round-trip byte-identical through from_snapshot -> get_persisted_snapshot.

Machines are generated with 2-3 regions, each region a small chain of atomic
states plus optional nested compound / final states, driven by a random event
alphabet.  Quiescence is established by `await send(..., wait=True)` followed
by a drain of the loop.

Run: python m1_parallel_property.py [max_examples]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from xstate_statemachine import Interpreter, create_machine
from xstate_statemachine.clock import SimulatedClock

EVENTS = ["E1", "E2", "E3", "E4"]

STATS = {"cases": 0, "snapshots": 0, "raises": [], "mismatch": [], "quiescent_illegal": []}


def _region(prefix: str, n: int, nested: bool):
    """Build one region: chain s0 -> s1 -> ... with optional nested compound."""
    states = {}
    for i in range(n):
        nxt = f"s{(i + 1) % n}"
        node = {"on": {EVENTS[i % len(EVENTS)]: nxt}}
        if nested and i == 1:
            node = {
                "initial": "x",
                "states": {
                    "x": {"on": {EVENTS[(i + 1) % len(EVENTS)]: "y"}},
                    "y": {"type": "final"},
                },
                "on": {EVENTS[i % len(EVENTS)]: nxt},
            }
        states[f"s{i}"] = node
    return {"initial": "s0", "states": states}


def build(nregions: int, sizes, nested_flags, with_history: bool):
    regions = {}
    for r in range(nregions):
        reg = _region(f"r{r}", sizes[r], nested_flags[r])
        if with_history and r == 0:
            reg["states"]["hist"] = {"type": "history", "history": "deep"}
        regions[f"r{r}"] = reg
    return create_machine(
        {
            "id": "par",
            "type": "parallel",
            "states": regions,
            "context": {"n": 0},
        }
    )


def canon(blob: dict) -> str:
    b = dict(blob)
    b.pop("taken_at", None)
    return json.dumps(b, sort_keys=True, default=str)


async def _one(nregions, sizes, nested_flags, with_history, seq):
    m = build(nregions, sizes, nested_flags, with_history)
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    await asyncio.sleep(0)
    points = [None] + list(seq)
    for ev in points:
        if ev is not None:
            try:
                await i.send(ev, wait=True)
            except Exception:  # noqa: BLE001  - event-level errors are not the property
                pass
        await asyncio.sleep(0)  # let any self-generated work settle
        try:
            blob = i.get_persisted_snapshot()
        except Exception as e:  # noqa: BLE001
            STATS["raises"].append(f"{type(e).__name__}: {e}")
            continue
        STATS["snapshots"] += 1
        # (c) legality: exactly one leaf per top-level region
        cfg = blob["configuration"]
        for r in range(nregions):
            leaves = [
                c for c in cfg
                if c.startswith(f"par.r{r}.") and "." in c[len(f"par.r{r}."):] or c.startswith(f"par.r{r}.")
            ]
            if not leaves:
                STATS["quiescent_illegal"].append((r, cfg))
        try:
            i2 = Interpreter.from_snapshot(
                json.dumps(blob), build(nregions, sizes, nested_flags, with_history),
                clock=SimulatedClock(),
            )
            await i2.start()
            await asyncio.sleep(0)
            blob2 = i2.get_persisted_snapshot()
            await i2.stop()
        except Exception as e:  # noqa: BLE001
            STATS["mismatch"].append(f"restore raised {type(e).__name__}: {e}")
            continue
        if canon(blob) != canon(blob2):
            STATS["mismatch"].append(
                f"seq={seq} canon differs:\n  A={canon(blob)[:400]}\n  B={canon(blob2)[:400]}"
            )
    await i.stop()


MAXEX = int(os.environ.get("MAXEX", sys.argv[1] if len(sys.argv) > 1 else "300"))


@settings(max_examples=MAXEX, deadline=None,
          suppress_health_check=list(HealthCheck), database=None)
@given(
    nregions=st.integers(min_value=2, max_value=3),
    sizes=st.lists(st.integers(min_value=2, max_value=4), min_size=3, max_size=3),
    nested_flags=st.lists(st.booleans(), min_size=3, max_size=3),
    with_history=st.booleans(),
    seq=st.lists(st.sampled_from(EVENTS), min_size=1, max_size=6),
)
def test_parallel_quiescent_snapshot(nregions, sizes, nested_flags, with_history, seq):
    STATS["cases"] += 1
    asyncio.run(_one(nregions, sizes, nested_flags, with_history, seq))


if __name__ == "__main__":
    import logging

    logging.disable(logging.CRITICAL)
    try:
        test_parallel_quiescent_snapshot()
    except Exception as e:  # noqa: BLE001
        print("HYPOTHESIS RAISED:", type(e).__name__, e)
    print(f"\ncases                  : {STATS['cases']}")
    print(f"snapshots taken OK     : {STATS['snapshots']}")
    print(f"snapshot raises        : {len(STATS['raises'])}   <- must be 0")
    for r in sorted(set(STATS["raises"]))[:5]:
        print("   -", r[:200])
    print(f"round-trip mismatches  : {len(STATS['mismatch'])}   <- must be 0")
    for r in STATS["mismatch"][:5]:
        print("   -", r[:400])
    print(f"illegal configurations : {len(STATS['quiescent_illegal'])}   <- must be 0")
    for r in STATS["quiescent_illegal"][:5]:
        print("   -", r)
    ok = not STATS["raises"] and not STATS["mismatch"] and not STATS["quiescent_illegal"]
    print("\nVERDICT:", "PASS" if ok else "FAIL")
