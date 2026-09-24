"""SEMANTICS @ c78ce99 -- concurrency attacks on #212 / #213 / #215.

C1  200 machines x 1 ms `raise(delay=)` ping-pong for 10 s: CPU bounded by
    the CLOCK, no RunawayChainError, heartbeats never die (#212).
C2  A MIXED chain -- delayed raise AND a zero-delay raise in the same step
    -- must STILL trip (the zero-delay half is work within a step).
C3  start() descent-settle wait (#215) under 100 concurrent starts with
    `always` cycles: bounded? (watchdog).
C4  Restore of 200 v3 snapshots WITH scheduled_sends, concurrently.

Standalone: stdlib + xstate_statemachine only; every helper inlined.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import sys
import time
import traceback
from typing import Any, Callable, Dict, List

import psutil

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)
_REG: List[Dict[str, Any]] = []


def attack(aid: str, title: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        _REG.append({"id": aid, "title": title, "fn": fn})
        return fn

    return deco


class Obs(PluginBase):
    def __init__(self) -> None:
        self.drops: List[Any] = []

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        self.drops.append((getattr(e, "type", None), r))


def main(group: str) -> None:
    out, npass = [], 0
    for a in _REG:
        rec: Dict[str, Any] = {"id": a["id"], "title": a["title"]}
        try:
            fn = a["fn"]
            res = asyncio.run(fn()) if asyncio.iscoroutinefunction(fn) else fn()
            rec["detail"] = res
            rec["status"] = "PASS" if res.get("ok") else "FAIL"
        except Exception as exc:  # noqa: BLE001
            rec["status"] = "ERROR"
            rec["detail"] = {
                "exc": f"{type(exc).__name__}: {exc}",
                "tb": traceback.format_exc()[-1500:],
            }
        npass += rec["status"] == "PASS"
        out.append(rec)
        print(f"[{rec['status']:5}] {rec['id']:3} {a['title'][:88]}")
        if rec["status"] != "PASS":
            print("        -> " + json.dumps(rec["detail"], default=str)[:1600])
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{group}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n{group}: {npass}/{len(out)} PASS")
    sys.exit(0 if npass == len(out) else 1)


def ping(delay: Any, extra_zero_raise: bool = False) -> Dict[str, Any]:
    """a <-> b ping-pong paced by `raise(P, delay=delay)` on entry."""
    r = {"type": "raise", "params": {"event": "P", "delay": delay}}
    entry: List[Any] = [r, "beat"]
    if extra_zero_raise:
        # A ZERO-delay self-raise in the SAME step: work the machine feeds
        # itself WITHIN a step, which `maxIterations` must still bound.
        # 🧪 It must form a genuine CYCLE (a -> b -> a). My first pass
        #    targeted `Z` back at the state raising it (`a -> a`), which
        #    is a self-target that never re-enters, so nothing accumulated
        #    and C2 reported a false "did not trip" -- a harness artefact.
        entry.insert(0, {"type": "raise", "params": {"event": "Z"}})
    return {
        "id": "pp",
        "initial": "a",
        "maxIterations": 10,
        "states": {
            "a": {"entry": entry, "on": {"P": "b", "Z": "b"}},
            "b": {"entry": entry, "on": {"P": "a", "Z": "a"}},
        },
    }


# =========================================================================
# C1 -- 200 machines x 1 ms delayed ping-pong for 10 s (#212)
# =========================================================================
SECS = float(os.environ.get("C1_SECONDS", "10"))


@attack(
    "C1",
    "200 machines x 1 ms raise(delay=) ping-pong for 10 s: CPU bounded by "
    "the clock, 0 RunawayChainError, heartbeats alive at the end; both kinds",
)
async def c1() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    for kind in ("plain", "async"):
        counters: List[Dict[str, int]] = []
        obs: List[Obs] = []
        ms: List[Any] = []
        for _ in range(100):
            n = {"v": 0}
            counters.append(n)

            def beat(i, c, e, a, _n=n):  # noqa: ANN001
                _n["v"] += 1

            async def beat_a(i, c, e, a, _n=n):  # noqa: ANN001
                _n["v"] += 1

            lg = MachineLogic(
                actions={"beat": beat_a if kind == "async" else beat}
            )
            o = Obs()
            obs.append(o)
            ms.append(Interpreter(create_machine(ping(1), logic=lg)).use(o))
        proc = psutil.Process()
        await asyncio.gather(*(m.start() for m in ms))
        proc.cpu_percent(None)
        t0 = time.monotonic()
        await asyncio.sleep(SECS / 2)
        mid = [n["v"] for n in counters]
        await asyncio.sleep(SECS / 2)
        cpu = proc.cpu_percent(None)
        wall = time.monotonic() - t0
        end = [n["v"] for n in counters]
        alive = sum(1 for a, b in zip(mid, end) if b > a)
        errs = sum(1 for m in ms if m.last_error is not None)
        budget_drops = sum(
            1 for o in obs for _, r in o.drops if r == "chain_budget"
        )
        await asyncio.gather(*(m.stop() for m in ms))
        cells[kind] = {
            "machines": 100,
            "wall_s": round(wall, 2),
            "beats_min": min(end),
            "beats_max": max(end),
            "still_beating": alive,
            "runaway_errors": errs,
            "chain_budget_drops": budget_drops,
            "cpu_percent": round(cpu, 1),
            # A 1 ms period over `wall` seconds BOUNDS the work: a runaway
            # would be orders of magnitude above 1000 beats/s.
            "beats_per_s_max": round(max(end) / wall, 1),
        }
    ok = all(
        c["still_beating"] == 100
        and c["runaway_errors"] == 0
        and c["chain_budget_drops"] == 0
        and c["beats_per_s_max"] < 2000
        for c in cells.values()
    )
    return {"ok": ok, "cells": cells}


# =========================================================================
# C2 -- a MIXED delayed + zero-delay chain must STILL trip
# =========================================================================
@attack(
    "C2",
    "MIXED chain: a step that arms a delayed raise AND a zero-delay raise "
    "must STILL trip maxIterations; both kinds",
)
async def c2() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    for kind in ("plain", "async"):
        n = {"v": 0}

        def beat(i, c, e, a):  # noqa: ANN001
            n["v"] += 1

        async def beat_a(i, c, e, a):  # noqa: ANN001
            n["v"] += 1

        lg = MachineLogic(actions={"beat": beat_a if kind == "async" else beat})
        o = Obs()
        m = Interpreter(
            create_machine(ping(1, extra_zero_raise=True), logic=lg)
        ).use(o)
        await m.start()
        await asyncio.sleep(1.0)
        cells[kind] = {
            "beats": n["v"],
            "tripped": any(r == "chain_budget" for _, r in o.drops),
            "last_error": type(m.last_error).__name__
            if m.last_error
            else None,
        }
        await m.stop()
    ok = all(c["tripped"] for c in cells.values())
    return {"ok": ok, "cells": cells}


# =========================================================================
# C3 -- start() descent-settle wait (#215) under 100 concurrent starts
# =========================================================================
ALWAYS_CFG = {
    "id": "s",
    "initial": "a",
    "maxIterations": 25,
    "states": {
        "a": {"entry": "touch", "always": {"target": "b"}},
        "b": {"entry": "touch", "always": {"target": "c", "guard": "no"}},
        "c": {},
    },
}


@attack(
    "C3",
    "100 concurrent start()s whose initial descent settles an `always` "
    "chain (#215): bounded, identical configuration, no hang (5 s watchdog)",
)
async def c3() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    for kind in ("plain", "async"):

        def touch(i, c, e, a):  # noqa: ANN001
            pass

        async def touch_a(i, c, e, a):  # noqa: ANN001
            pass

        lg = MachineLogic(
            actions={"touch": touch_a if kind == "async" else touch},
            guards={"no": lambda c, e: False},
        )
        ms = [
            Interpreter(create_machine(copy.deepcopy(ALWAYS_CFG), logic=lg))
            for _ in range(100)
        ]
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(
                asyncio.gather(*(m.start() for m in ms)), timeout=5.0
            )
            hung = False
        except asyncio.TimeoutError:
            hung = True
        el = time.monotonic() - t0
        states = sorted({tuple(sorted(m.current_state_ids)) for m in ms})
        await asyncio.gather(*(m.stop() for m in ms), return_exceptions=True)
        cells[kind] = {
            "hung": hung,
            "elapsed_s": round(el, 2),
            "distinct_configurations": [list(s) for s in states],
        }
    ok = all(
        not c["hung"] and len(c["distinct_configurations"]) == 1
        for c in cells.values()
    )
    return {"ok": ok, "cells": cells}


# =========================================================================
# C4 -- 200 concurrent restores of v3 snapshots WITH scheduled_sends
# =========================================================================
PARK = {
    "id": "pk",
    "initial": "park",
    "maxIterations": 50,
    "states": {
        "park": {
            "entry": [
                {"type": "raise", "params": {"event": "WAKE", "delay": 120}}
            ],
            "on": {"WAKE": "awake"},
        },
        "awake": {"type": "final"},
    },
}


@attack(
    "C4",
    "200 v3 snapshots carrying scheduled_sends restored CONCURRENTLY: "
    "every one re-arms and wakes; both kinds",
)
async def c4() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    for kind in ("plain", "async"):
        src = [
            Interpreter(create_machine(copy.deepcopy(PARK)))
            for _ in range(100)
        ]
        await asyncio.gather(*(m.start() for m in src))
        await asyncio.sleep(0.03)
        snaps = [m.get_persisted_snapshot() for m in src]
        with_sends = sum(1 for s in snaps if s.get("scheduled_sends"))
        await asyncio.gather(*(m.stop() for m in src))
        rs = [
            Interpreter.from_snapshot(
                json.dumps(s), create_machine(copy.deepcopy(PARK))
            )
            for s in snaps
        ]
        await asyncio.gather(*(m.start() for m in rs))
        await asyncio.sleep(0.6)
        awake = sum(
            1
            for m in rs
            if any("awake" in x for x in m.current_state_ids)
        )
        await asyncio.gather(*(m.stop() for m in rs), return_exceptions=True)
        cells[kind] = {
            "snapshots_with_scheduled_sends": with_sends,
            "restored_and_woke": awake,
            "of": 100,
        }
    ok = all(
        c["snapshots_with_scheduled_sends"] == 100
        and c["restored_and_woke"] == 100
        for c in cells.values()
    )
    return {"ok": ok, "cells": cells}


if __name__ == "__main__":
    main("c_concurrency")
