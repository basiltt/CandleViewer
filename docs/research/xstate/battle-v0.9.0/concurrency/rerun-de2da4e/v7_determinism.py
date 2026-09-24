"""v7 (@de2da4e) -- STANDALONE. Determinism: 50x identical traces per
cell, both engines, both action kinds, INCLUDING the #222 chain_trips
count and the #221 parked-restore hop in the trace.

Each run produces a hash over (state-id sequence, context, chain_trips,
latched-error type, scheduled_sends record count at each hop). A cell is
deterministic iff all 50 runs hash equal.

Cells: {async, sync} x {def, async def} x {restore=False, restore=True}
where restore=True inserts the #221 chain persist -> restore ->
re-persist -> restore -> start mid-trace.

Run: python v7_determinism.py   (exit 1 == non-determinism)
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import sys
import time
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock

RUNS = 50
FAILS: List[str] = []
HERE = os.path.dirname(os.path.abspath(__file__))


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {
        "probe": name,
        "py": ".".join(map(str, sys.version_info[:3])),
        **data,
    }
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(HERE, name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def cfg() -> Dict[str, Any]:
    """One chart exercising all three round-11 mechanisms: an armed
    delayed self-send (#213/#221), a zero-delay cycle that trips the
    budget (#222) and a timer whose handle must be released (#218)."""
    return {
        "id": "v7",
        "initial": "arm",
        "context": {"n": 0},
        "maxIterations": 4,
        "states": {
            "arm": {
                "entry": [
                    {"type": "raise",
                     "params": {"event": "LATE", "delay": 500, "id": "hb"}},
                    "tick",
                ],
                "on": {"LATE": "spin", "KICK": "spin"},
            },
            "spin": {
                "entry": [{"type": "raise", "params": {"event": "GO"}},
                          "tick"],
                "on": {"GO": "spin2"},
            },
            "spin2": {
                "entry": [{"type": "raise", "params": {"event": "GO"}},
                          "tick"],
                "on": {"GO": "spin"},
            },
        },
    }


def logic(kind: str) -> MachineLogic:
    if kind == "def":

        def tick(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1

        return MachineLogic(actions={"tick": tick})

    async def atick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"tick": atick})


def blob_of(i: Any) -> str:
    s = i.get_persisted_snapshot()
    return s if isinstance(s, str) else json.dumps(s, default=str)


def digest(trace: List[Any]) -> str:
    return hashlib.sha256(
        json.dumps(trace, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


async def run_async(kind: str, restore: bool) -> str:
    trace: List[Any] = []
    c = SimulatedClock()
    i = Interpreter(create_machine(copy.deepcopy(cfg()), logic=logic(kind)),
                    clock=c)
    await i.start()
    trace.append(("start", sorted(i.current_state_ids)))
    trace.append(("sched", len(json.loads(blob_of(i)).get(
        "scheduled_sends") or [])))
    if restore:
        # 🔁 #221 chain: persist -> restore -> re-persist -> restore -> start
        b = blob_of(i)
        await i.stop()
        m1 = create_machine(copy.deepcopy(cfg()), logic=logic(kind))
        parked = Interpreter.from_snapshot(b, m1, clock=SimulatedClock())
        b2 = blob_of(parked)
        trace.append(("parked_sched",
                      len(json.loads(b2).get("scheduled_sends") or [])))
        c = SimulatedClock()
        m2 = create_machine(copy.deepcopy(cfg()), logic=logic(kind))
        i = Interpreter.from_snapshot(b2, m2, clock=c)
        await i.start()
        trace.append(("restored", sorted(i.current_state_ids)))
    await c.increment(600)            # fire the armed LATE -> trips the spin
    await asyncio.sleep(0.05)
    trace.append(("after_late", sorted(i.current_state_ids)))
    trace.append(("n", i.context.get("n")))
    trace.append(("chain_trips", i.chain_trips))
    trace.append(("latch", type(i.last_chain_error).__name__
                  if i.last_chain_error else None))
    await i.stop()
    return digest(trace)


def run_sync(kind: str, restore: bool) -> str:
    if kind == "async def":
        return "unsupported"
    trace: List[Any] = []
    c = SimulatedClock()
    i = SyncInterpreter(create_machine(copy.deepcopy(cfg()),
                                       logic=logic("def")), clock=c)
    i.start()
    trace.append(("start", sorted(i.current_state_ids)))
    trace.append(("sched", len(json.loads(blob_of(i)).get(
        "scheduled_sends") or [])))
    if restore:
        b = blob_of(i)
        try:
            i.stop()
        except Exception:  # noqa: BLE001
            pass
        m1 = create_machine(copy.deepcopy(cfg()), logic=logic("def"))
        parked = SyncInterpreter.from_snapshot(b, m1, clock=SimulatedClock())
        b2 = blob_of(parked)
        trace.append(("parked_sched",
                      len(json.loads(b2).get("scheduled_sends") or [])))
        c = SimulatedClock()
        m2 = create_machine(copy.deepcopy(cfg()), logic=logic("def"))
        i = SyncInterpreter.from_snapshot(b2, m2, clock=c)
        i.start()
        trace.append(("restored", sorted(i.current_state_ids)))
    c.increment(600)
    for _ in range(20):
        i.tick()
    trace.append(("after_late", sorted(i.current_state_ids)))
    trace.append(("n", i.context.get("n")))
    trace.append(("chain_trips", i.chain_trips))
    trace.append(("latch", type(i.last_chain_error).__name__
                  if i.last_chain_error else None))
    try:
        i.stop()
    except Exception:  # noqa: BLE001
        pass
    return digest(trace)


def sync_main() -> Dict[str, Any]:
    """🧷 The sync cells MUST run outside a running event loop:
    `SimulatedClock.increment()` warns and fires nothing when called from
    inside one, which would silently hash an un-advanced trace."""
    cells: Dict[str, Any] = {}
    for restore in (False, True):
        key = f"sync/def/restore={restore}"
        hashes = {run_sync("def", restore) for _ in range(RUNS)}
        cells[key] = sorted(hashes)
        if len(hashes) != 1:
            FAILS.append(f"{key}: {len(hashes)} distinct traces over "
                         f"{RUNS} runs -- NON-DETERMINISTIC")
    return cells


async def main(sync_cells: Dict[str, Any]) -> int:
    cells: Dict[str, Any] = {}
    t0 = time.perf_counter()
    for kind in ("def", "async def"):
        for restore in (False, True):
            key = f"async/{kind}/restore={restore}"
            hashes = {await run_async(kind, restore) for _ in range(RUNS)}
            cells[key] = sorted(hashes)
            if len(hashes) != 1:
                FAILS.append(f"{key}: {len(hashes)} distinct traces "
                             f"over {RUNS} runs -- NON-DETERMINISTIC")
    cells.update(sync_cells)
    # restore and no-restore must agree WITHIN an engine (#221 must not
    # perturb the trace) -- compared on the shared tail only, so this is
    # recorded rather than asserted (the traces carry different tuples).
    out = {
        "runs_per_cell": RUNS, "cells": cells,
        "wall_s": round(time.perf_counter() - t0, 1),
        "failures": FAILS,
        "verdict": "DEFECT" if FAILS else "CLEAN",
    }
    emit("v7_determinism", out)
    return 1 if FAILS else 0


if __name__ == "__main__":
    _sync = sync_main()
    sys.exit(asyncio.run(main(_sync)))
