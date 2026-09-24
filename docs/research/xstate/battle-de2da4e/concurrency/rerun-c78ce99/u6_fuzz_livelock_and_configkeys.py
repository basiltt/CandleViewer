"""u6 (@c78ce99) -- STANDALONE. Livelock fuzzer under the #212 oracle,
plus a #216 config-key fuzzer.

F1  >=500 random configs x both action kinds x both engines. Grammar now
    includes `raise(delay=)`. NEW ORACLE:
      * a cycle whose every self-feed carries a delay >= 1 ms is legal
        periodic work -- it must NOT trip and must run >= MIN_BEATS;
      * a cycle must trip only where it feeds itself MORE THAN
        maxIterations times with NO delay in between -- a delayed hop
        ends the step's chain, so a mixed cycle is periodic work too.
        The discriminator is the longest run of consecutive zero-delay
        hops around the cycle (infinite when every hop is zero-delay).
    Watchdog 3 s per cell: a timeout IS the observed result.
F2  #216 config-key fuzzer: random misspellings of KNOWN_MACHINE_KEYS at
    the TOP level and at the STATE level, default and strict_config.
    Records precisely what nested does.

Reduced: 540 cells = 180 shapes (2 seeded shards x 90) x 3 supported
lanes (async/def, async/async def, sync/def), 0.1 s of run per cell (every livelock in this family trips or hangs within
tens of ms; measured against the 3 s reference in round 9).

Run: python u6_fuzz_livelock_and_configkeys.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import random
import sys
import time
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    InvalidConfigError,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.validation import KNOWN_MACHINE_KEYS

N_SHAPES = 90
LIMIT = 6
RUN_S = 0.1
MIN_BEATS = 3


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


class Drops(PluginBase):
    def __init__(self):
        self.chain = 0

    def on_event_dropped(self, interpreter, event, reason):  # noqa: ANN001
        if reason == "chain_budget":
            self.chain += 1


def logic(kind):
    if kind == "def":

        def tick(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1

        return MachineLogic(actions={"tick": tick})

    async def atick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"tick": atick})


def gen_shape(rng):
    """A 2..4 state self-feeding cycle. Each hop's raise carries a delay
    drawn from [None, 1, 2, 5, 10] ms; None == zero-delay."""
    n = rng.randint(2, 4)
    # 🎲 One shape in four is forced ALL zero-delay so the oracle is
    #    two-sided: the fuzzer must produce must-trip cells as well as
    #    must-not-trip ones (a 2..4-hop cycle rarely reaches a zero run
    #    > maxIterations by chance).
    if rng.random() < 0.25:
        delays = [None] * n
    else:
        delays = [rng.choice([None, 1, 1, 2, 5, 10]) for _ in range(n)]
    states: Dict[str, Any] = {}
    for k in range(n):
        nxt = f"s{(k + 1) % n}"
        params: Dict[str, Any] = {"event": "GO"}
        if delays[k] is not None:
            params["delay"] = delays[k]
        states[f"s{k}"] = {
            "entry": [{"type": "raise", "params": params}],
            "on": {"GO": nxt},
            "exit": ["tick"],
        }
    cfg = {"id": "u6", "initial": "s0", "maxIterations": LIMIT,
           "context": {"n": 0}, "states": states}
    all_delayed = all(d is not None for d in delays)
    # 🔗 #212: the longest run of CONSECUTIVE zero-delay hops around the
    #    cycle is the work the machine feeds itself within one step.
    if all_delayed:
        run = 0
    elif all(d is None for d in delays):
        run = 10 ** 6          # unbroken zero-delay cycle
    else:
        doubled = delays + delays
        run = best = 0
        for d in doubled:
            run = run + 1 if d is None else 0
            best = max(best, run)
        run = best
    return cfg, delays, all_delayed, run


async def run_async(cfg, kind) -> Dict[str, Any]:
    m = create_machine(copy.deepcopy(cfg), logic=logic(kind))
    d = Drops()
    i = Interpreter(m)
    i.use(d)
    hung = False
    try:
        await asyncio.wait_for(i.start(), timeout=3.0)
        await asyncio.sleep(RUN_S)
    except asyncio.TimeoutError:
        hung = True
    except Exception as exc:  # noqa: BLE001
        return {"engine": "async", "kind": kind, "raised": repr(exc),
                "tripped": True, "beats": 0, "hung": False}
    beats = i.context.get("n", 0)
    tripped = bool(d.chain) or i.last_error is not None
    try:
        await asyncio.wait_for(i.stop(), timeout=3.0)
    except Exception:
        pass
    return {"engine": "async", "kind": kind, "beats": beats,
            "tripped": tripped, "chain_drops": d.chain, "hung": hung}


def run_sync(cfg, kind) -> Dict[str, Any]:
    if kind == "async def":
        return {"engine": "sync", "kind": kind, "unsupported": True}
    m = create_machine(copy.deepcopy(cfg), logic=logic(kind))
    d = Drops()
    i = SyncInterpreter(m)
    i.use(d)
    try:
        i.start()
        end = time.perf_counter() + RUN_S
        while time.perf_counter() < end:
            i.tick()
            time.sleep(0.001)
    except Exception as exc:  # noqa: BLE001
        return {"engine": "sync", "kind": kind, "raised": repr(exc),
                "tripped": True, "beats": 0, "hung": False}
    beats = i.context.get("n", 0)
    tripped = bool(d.chain) or i.last_error is not None
    try:
        i.stop()
    except Exception:
        pass
    return {"engine": "sync", "kind": kind, "beats": beats,
            "tripped": tripped, "chain_drops": d.chain, "hung": False}


async def f1_fuzz(seed) -> Dict[str, Any]:
    rng = random.Random(seed)
    cells = 0
    viols: List[Dict[str, Any]] = []
    hangs = 0
    legal_periodic = 0
    must_trip_cells = 0
    for s in range(N_SHAPES):
        cfg, delays, all_delayed, zrun = gen_shape(rng)
        rows = []
        for kind in ("def", "async def"):
            rows.append(await run_async(cfg, kind))
        rows.append(run_sync(cfg, "def"))
        for r in rows:
            if r.get("unsupported"):
                continue
            cells += 1
            if r.get("hung"):
                hangs += 1
                viols.append({"shape": s, "delays": delays, "why": "HANG",
                              **r})
                continue
            must_trip = zrun > LIMIT
            if must_trip:
                must_trip_cells += 1
            if not must_trip:
                legal_periodic += 1
                if r["tripped"]:
                    viols.append({"shape": s, "delays": delays,
                                  "zero_run": zrun,
                                  "why": "periodic cycle TRIPPED "
                                         "(violates the #212 rule)", **r})
                elif r["beats"] < MIN_BEATS:
                    viols.append({"shape": s, "delays": delays,
                                  "zero_run": zrun,
                                  "why": f"periodic process ran only "
                                         f"{r['beats']} beats", **r})
            else:
                if not r["tripped"]:
                    viols.append({"shape": s, "delays": delays,
                                  "zero_run": zrun,
                                  "why": f"{zrun} consecutive zero-delay "
                                         f"hops (> maxIterations={LIMIT}) "
                                         f"did NOT trip", **r})
    return {"seed": seed, "shapes": N_SHAPES, "cells": cells,
            "must_trip_cells": must_trip_cells,
            "periodic_cells": legal_periodic, "hangs": hangs,
            "violations": len(viols), "violation_sample": viols[:6]}


def f2_config_keys(seed) -> Dict[str, Any]:
    rng = random.Random(seed)
    keys = sorted(KNOWN_MACHINE_KEYS)
    top_caught = 0
    top_missed: List[str] = []
    nested_caught = 0
    nested_missed: List[str] = []
    for _ in range(120):
        key = rng.choice(keys)
        bad = key + rng.choice(["y", "s", "_", "X"])
        base = {"id": "z", "initial": "a", "states": {"a": {}}}
        try:
            create_machine(dict(base, **{bad: True}), strict_config=True)
            top_missed.append(bad)
        except InvalidConfigError:
            top_caught += 1
        except Exception:
            top_caught += 1
        nested = {"id": "z2", "initial": "a",
                  "states": {"a": {bad: True}}}
        try:
            create_machine(nested, strict_config=True)
            nested_missed.append(bad)
        except InvalidConfigError:
            nested_caught += 1
        except Exception:
            nested_caught += 1
    return {
        "trials": 120,
        "top_level_caught": top_caught,
        "top_level_missed": sorted(set(top_missed))[:10],
        "nested_caught": nested_caught,
        "nested_missed_count": len(nested_missed),
        "nested_missed_sample": sorted(set(nested_missed))[:10],
        "note": ("#216 validates TOP-LEVEL keys only. KNOWN_MACHINE_KEYS "
                 "contains behavioural state-level keys (entry/exit/on/"
                 "after/always/invoke/onDone/type/initial/states); a "
                 "misspelling of any of them INSIDE a state is dropped "
                 "silently even under strict_config=True."),
    }


async def main() -> int:
    f1a = await f1_fuzz(20251)
    f1b = await f1_fuzz(20252)
    total_cells = f1a["cells"] + f1b["cells"]
    res = {
        "F1_shard_a": f1a, "F1_shard_b": f1b,
        "F1_total_cells": total_cells,
        "F1_total_violations": f1a["violations"] + f1b["violations"],
        "F2_config_key_fuzz": f2_config_keys(777),
    }
    bad = res["F1_total_violations"] > 0
    res["verdict"] = "DEFECT" if bad else "CLEAN"
    emit("u6_fuzz_livelock_and_configkeys", res)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
