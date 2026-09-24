"""SEMANTICS @ c78ce99 -- livelock fuzzer with the #212 oracle.

F1  >=500 configs x {def, async def} x {sync, async engine} over cycle
    shapes: `always`, `raise0` (zero-delay), `raise_delay` (>=1 ms),
    `after`, `invoke`, and MIXED (delayed + zero-delay in one step).

    🎯 The ORACLE CHANGED this round (#212 supersedes #206):
      * a cycle whose ONLY self-feeding is a delay >= 1 ms is LEGAL
        PERIODIC WORK -- it must NOT trip, and it must still be beating
        after N beats (liveness, not just "no exception");
      * a ZERO-delay cycle must TRIP;
      * a MIXED cycle (both in one step) must TRIP on the zero-delay half.

    Every run is watchdogged; a timeout IS the observed result.

Standalone: stdlib + xstate_statemachine only; every helper inlined.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import random
import sys
import traceback
from typing import Any, Callable, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)

N_CONFIGS = int(os.environ.get("F1_CONFIGS", "500"))
WATCHDOG_S = float(os.environ.get("F1_WATCHDOG", "3.0"))

# Cycle shapes and what the post-#212 oracle demands of each.
#   "trip"      -> must trip maxIterations (self-fed work within a step)
#   "periodic"  -> must NOT trip and must still be beating (clock-paced)
SHAPES = {
    "always": "trip",
    "raise0": "trip",
    "raise_delay": "periodic",
    "after": "periodic",
    "mixed": "trip",
    "invoke": "trip",
}


class Obs(PluginBase):
    def __init__(self) -> None:
        self.budget_drops = 0

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        if r == "chain_budget":
            self.budget_drops += 1


def build(shape: str, rng: random.Random, n: int) -> Dict[str, Any]:
    """A two-state cycle of the given shape; `beat` counts laps."""
    limit = rng.choice([5, 8, 10, 15, 25])
    delay = rng.choice([1, 2, 5, 10])
    r0 = {"type": "raise", "params": {"event": "Z"}}
    rd = {"type": "raise", "params": {"event": "P", "delay": delay}}
    cfg: Dict[str, Any] = {
        "id": f"f{n}",
        "initial": "a",
        "maxIterations": limit,
        "states": {"a": {}, "b": {}},
    }
    for here, there in (("a", "b"), ("b", "a")):
        s = cfg["states"][here]
        if shape == "always":
            s["entry"] = "beat"
            s["always"] = {"target": there}
        elif shape == "raise0":
            s["entry"] = [r0, "beat"]
            s["on"] = {"Z": there}
        elif shape == "raise_delay":
            s["entry"] = [copy.deepcopy(rd), "beat"]
            s["on"] = {"P": there}
        elif shape == "mixed":
            s["entry"] = [r0, copy.deepcopy(rd), "beat"]
            s["on"] = {"Z": there, "P": there}
        elif shape == "after":
            s["entry"] = "beat"
            s["after"] = {delay: there}
        elif shape == "invoke":
            s["entry"] = "beat"
            s["invoke"] = {"src": "svc", "id": f"s{here}", "onDone": there}
    return cfg


async def run_async(cfg: Dict[str, Any], kind: str) -> Dict[str, Any]:
    n = {"v": 0}

    def beat(i, c, e, a):  # noqa: ANN001
        n["v"] += 1

    async def beat_a(i, c, e, a):  # noqa: ANN001
        n["v"] += 1

    def svc(i, c, e):  # noqa: ANN001
        return 1

    async def svc_a(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return 1

    lg = MachineLogic(
        actions={"beat": beat_a if kind == "async" else beat},
        services={"svc": svc_a if kind == "async" else svc},
    )
    o = Obs()
    m = Interpreter(create_machine(cfg, logic=lg)).use(o)
    await m.start()
    await asyncio.sleep(0.35)
    mid = n["v"]
    await asyncio.sleep(0.35)
    res = {
        "beats": n["v"],
        "still_beating": n["v"] > mid,
        "tripped": o.budget_drops > 0 or m.last_error is not None,
    }
    await m.stop()
    return res


def run_sync(cfg: Dict[str, Any], kind: str) -> Dict[str, Any]:
    n = {"v": 0}

    def beat(i, c, e, a):  # noqa: ANN001
        n["v"] += 1

    def svc(i, c, e):  # noqa: ANN001
        return 1

    lg = MachineLogic(actions={"beat": beat}, services={"svc": svc})
    o = Obs()
    m = SyncInterpreter(create_machine(cfg, logic=lg)).use(o)
    try:
        m.start()
    except Exception:  # noqa: BLE001
        pass
    res = {
        "beats": n["v"],
        "still_beating": None,  # not meaningful: the caller drives the clock
        "tripped": o.budget_drops > 0 or m.last_error is not None,
    }
    try:
        m.stop()
    except Exception:  # noqa: BLE001
        pass
    return res


async def main() -> int:
    rng = random.Random(778899)
    shapes = list(SHAPES)
    findings: List[Dict[str, Any]] = []
    runs = 0
    hangs = 0
    tally: Dict[str, Dict[str, int]] = {
        s: {"runs": 0, "tripped": 0, "periodic_alive": 0} for s in shapes
    }
    for i in range(N_CONFIGS):
        shape = shapes[i % len(shapes)]
        cfg = build(shape, rng, i)
        want = SHAPES[shape]
        for kind in ("plain", "async"):
            runs += 1
            tally[shape]["runs"] += 1
            try:
                r = await asyncio.wait_for(
                    run_async(copy.deepcopy(cfg), kind), timeout=WATCHDOG_S
                )
            except asyncio.TimeoutError:
                hangs += 1
                findings.append(
                    {"i": i, "shape": shape, "kind": kind, "why": "HANG"}
                )
                continue
            except Exception as exc:  # noqa: BLE001
                findings.append(
                    {"i": i, "shape": shape, "kind": kind,
                     "why": f"EXC {type(exc).__name__}: {exc}"[:120]}
                )
                continue
            if r["tripped"]:
                tally[shape]["tripped"] += 1
            if want == "trip" and not r["tripped"]:
                findings.append(
                    {"i": i, "shape": shape, "kind": kind,
                     "why": "SILENT RUNAWAY: zero-delay cycle did not trip",
                     "r": r}
                )
            if want == "periodic":
                # 🎯 #212: clock-paced work must NOT trip AND must still be
                #    running -- "no exception" alone would pass a machine
                #    that quietly died at maxIterations beats.
                if r["tripped"]:
                    findings.append(
                        {"i": i, "shape": shape, "kind": kind,
                         "why": "PERIODIC WORK CUT (violates #212)", "r": r}
                    )
                elif not r["still_beating"]:
                    findings.append(
                        {"i": i, "shape": shape, "kind": kind,
                         "why": "PERIODIC WORK DIED (violates #212)", "r": r}
                    )
                else:
                    tally[shape]["periodic_alive"] += 1
        # -- sync engine: only the shapes it drives inside one start()/send.
        if shape in ("always", "raise0", "mixed", "invoke"):
            runs += 1
            try:
                rs = run_sync(copy.deepcopy(cfg), "plain")
                if SHAPES[shape] == "trip" and not rs["tripped"]:
                    findings.append(
                        {"i": i, "shape": shape, "kind": "sync_engine",
                         "why": "SILENT RUNAWAY on sync engine", "r": rs}
                    )
            except Exception as exc:  # noqa: BLE001
                findings.append(
                    {"i": i, "shape": shape, "kind": "sync_engine",
                     "why": f"EXC {type(exc).__name__}: {exc}"[:120]}
                )
    out = {
        "ok": not findings,
        "configs": N_CONFIGS,
        "runs": runs,
        "hangs": hangs,
        "n_findings": len(findings),
        "findings": findings[:12],
        "per_shape": tally,
        "oracle": {k: SHAPES[k] for k in SHAPES},
    }
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "f_fuzz.json"), "w", encoding="utf-8") as fh:
        json.dump([{"id": "F1", "status": "PASS" if out["ok"] else "FAIL",
                    "detail": out}], fh, indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items()
                      if k != "findings"}, indent=1))
    if findings:
        print("FINDINGS:", json.dumps(findings[:12], indent=1, default=str))
    print(f"\nf_fuzz: {'PASS' if out['ok'] else 'FAIL'} "
          f"({runs} runs, {hangs} hangs)")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
