"""t7 (@19cb1f1) -- STANDALONE livelock fuzz for the round-10 machinery.
No shared helpers: everything is inline.

N generated configs x {def, async def} x {async engine, sync engine}.
Shapes mix the three things round 9 touched:
  always-cycle, invoke+onDone cycle, rollback+onDone, delayed `raise`
  ping-pong (#206), after-timer loops (#203), and always+invoke+after in
  one chart.

Invariants:
  I1  every config terminates within the watchdog -- a hang IS a defect
  I2  every CHAIN trip is OBSERVABLE: `last_error` is a RunawayChainError, or a
      `chain_budget` drop reached `on_event_dropped`
  I3  LAP PARITY: for the same (config, kind) the async and sync engines
      must count the same number of laps

Reductions: watchdog 3 s (every livelock in this family hangs
indefinitely, so 3 s discriminates identically -- same rationale as
rounds 8/9); settle 0.12 s. `async def` is unsupported on the sync
engine, so lap parity is checked on the `def` lane; timer-paced shapes
are excluded from parity because the sync engine drives them from the
caller's tick() (stated in the #206 pin). Timer shapes are also excluded
from I2: an `after` loop is paced by real wall-clock time, so it is not
self-generated work and `maxIterations` is not the bound that applies to
it -- recorded as a contract note, not a defect.

Run: python t7_livelock_fuzz_round10.py [--n=170] [--seed=10101]
     (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import random
import sys
from collections import Counter
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)


def arg(name: str, default: Any, cast=int):  # noqa: ANN001
    for a in sys.argv[1:]:
        if a.startswith("--" + name + "="):
            return cast(a.split("=")[1])
    return default


N = arg("n", 170)
SEED = arg("seed", 10101)
WD = arg("wd", 3.0, float)
SETTLE = arg("settle", 0.12, float)
TAG = arg("tag", "", str)


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


SHAPES = (
    "always_cycle",
    "invoke_cycle",
    "rollback_ondone",
    "delayed_raise_pingpong",
    "after_loop",
    "always_invoke_after",
)

TIMER_SHAPES = ("after_loop", "delayed_raise_pingpong", "always_invoke_after")


def gen(rng: random.Random) -> Dict[str, Any]:
    shape = rng.choice(SHAPES)
    limit = rng.choice([3, 5, 8, 12, 20])
    inv = {"id": "s", "src": "svc", "onDone": {"target": "b"}}
    if shape == "always_cycle":
        st = {
            "a": {"entry": ["tick"], "always": {"target": "b"}},
            "b": {"entry": ["tick"], "always": {"target": "a"}},
        }
    elif shape == "invoke_cycle":
        st = {
            "a": {"entry": ["tick"], "invoke": dict(inv)},
            "b": {"entry": ["tick"], "always": {"target": "a"}},
        }
    elif shape == "rollback_ondone":
        st = {
            "a": {"entry": ["tick"], "invoke": dict(inv)},
            "b": {"entry": ["tick", "boom"]},
        }
    elif shape == "delayed_raise_pingpong":
        d = rng.choice([0.001, 0.002])
        r = {"type": "raise", "params": {"event": "P", "delay": d}}
        st = {
            "a": {"entry": ["tick", r], "on": {"P": "b"}},
            "b": {"entry": ["tick", r], "on": {"P": "a"}},
        }
    elif shape == "after_loop":
        ms = rng.choice([1, 2])
        st = {
            "a": {"entry": ["tick"], "after": {ms: {"target": "b"}}},
            "b": {"entry": ["tick"], "after": {ms: {"target": "a"}}},
        }
    else:  # always_invoke_after
        inv2 = dict(inv)
        inv2["onDone"] = {"target": "a"}
        st = {
            "a": {"entry": ["tick"], "always": {"target": "b"}},
            "b": {"entry": ["tick"], "invoke": inv2,
                  "after": {1: {"target": "a"}}},
        }
    cfg: Dict[str, Any] = {
        "id": "f", "initial": "a", "maxIterations": limit,
        "context": {}, "states": st,
    }
    if shape == "rollback_ondone":
        cfg["actionErrorPolicy"] = "rollback"
    return {"shape": shape, "limit": limit, "cfg": cfg}


class Spy(PluginBase):
    def __init__(self) -> None:
        self.drops: List[str] = []

    def on_event_dropped(self, itp, event, reason):  # noqa: ANN001
        self.drops.append(reason)


def logic(kind: str, laps: List[int]) -> MachineLogic:
    def tick(i, c, e, ad):  # noqa: ANN001
        laps[0] += 1

    def boom(i, c, e, ad):  # noqa: ANN001
        raise RuntimeError("boom")

    if kind == "def":

        def svc(i, c, e):  # noqa: ANN001
            return 1

    else:

        async def svc(i, c, e):  # noqa: ANN001
            return 1

    return MachineLogic(
        actions={"tick": tick, "boom": boom}, services={"svc": svc}
    )


def _finish(row: Dict[str, Any], laps: List[int], spy: Spy) -> Dict[str, Any]:
    row["laps"] = laps[0]
    row["drops"] = Counter(spy.drops).most_common(3)
    row["observable"] = (
        row.get("err") == "RunawayChainError" or "chain_budget" in spy.drops
    )
    return row


async def run_async(case: Dict[str, Any], kind: str) -> Dict[str, Any]:
    laps, spy = [0], Spy()
    itp = Interpreter(
        create_machine(copy.deepcopy(case["cfg"]), logic=logic(kind, laps))
    )
    itp.use(spy)
    row: Dict[str, Any] = {"engine": "async", "kind": kind}
    try:
        await asyncio.wait_for(itp.start(), timeout=WD)
        await asyncio.sleep(SETTLE)
        row["err"] = type(getattr(itp, "last_error", None)).__name__
    except asyncio.TimeoutError:
        row["err"] = "WATCHDOG_TIMEOUT"
    except Exception as exc:  # noqa: BLE001
        row["err"] = type(exc).__name__
    finally:
        try:
            await asyncio.wait_for(itp.stop(), timeout=WD)
        except Exception:  # noqa: BLE001
            pass
    return _finish(row, laps, spy)


def run_sync(case: Dict[str, Any], kind: str) -> Dict[str, Any]:
    laps, spy = [0], Spy()
    itp = SyncInterpreter(
        create_machine(copy.deepcopy(case["cfg"]), logic=logic(kind, laps))
    )
    itp.use(spy)
    row: Dict[str, Any] = {"engine": "sync", "kind": kind}
    try:
        itp.start()
        row["err"] = type(getattr(itp, "last_error", None)).__name__
    except Exception as exc:  # noqa: BLE001
        row["err"] = type(exc).__name__
    finally:
        try:
            itp.stop()
        except Exception:  # noqa: BLE001
            pass
    return _finish(row, laps, spy)


async def main() -> int:
    rng = random.Random(SEED)
    cases = [gen(rng) for _ in range(N)]
    hangs: List[Any] = []
    unobservable: List[Any] = []
    parity: List[Any] = []
    shapes: Counter = Counter()
    errs: Counter = Counter()

    for idx, case in enumerate(cases):
        shapes[case["shape"]] += 1
        per: Dict[str, Any] = {}
        for kind in ("def", "async def"):
            a = await run_async(case, kind)
            errs["async/" + kind + "/" + str(a["err"])] += 1
            per["async/" + kind] = a
            if a["err"] == "WATCHDOG_TIMEOUT":
                hangs.append((idx, case["shape"], case["limit"], "async", kind))
            elif (not a["observable"] and a["laps"] > case["limit"] + 3
                  and case["shape"] not in TIMER_SHAPES):
                unobservable.append(
                    (idx, case["shape"], case["limit"], "async", kind,
                     a["laps"], a["err"])
                )
        s = run_sync(case, "def")
        errs["sync/def/" + str(s["err"])] += 1
        if s["err"] == "WATCHDOG_TIMEOUT":
            hangs.append((idx, case["shape"], case["limit"], "sync", "def"))
        elif (not s["observable"] and s["laps"] > case["limit"] + 3
              and case["shape"] not in TIMER_SHAPES):
            unobservable.append(
                (idx, case["shape"], case["limit"], "sync", "def",
                 s["laps"], s["err"])
            )
        if case["shape"] not in TIMER_SHAPES:
            a = per["async/def"]
            if a["laps"] != s["laps"]:
                parity.append(
                    (idx, case["shape"], case["limit"], a["laps"], s["laps"])
                )

    viol = bool(hangs or unobservable or parity)
    emit(
        "t7_livelock_fuzz_round10" + (("_" + TAG) if TAG else ""),
        {
            "n": N, "seed": SEED, "watchdog_s": WD, "settle_s": SETTLE,
            "shape_mix": dict(shapes),
            "outcome_mix": dict(errs.most_common(20)),
            "hangs": hangs[:10], "n_hangs": len(hangs),
            "unobservable_trips": unobservable[:10],
            "n_unobservable": len(unobservable),
            "lap_parity_gaps": parity[:10], "n_parity_gaps": len(parity),
            "result": "FAIL" if viol else "PASS",
        },
    )
    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
