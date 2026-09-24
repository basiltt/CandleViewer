"""R10 - determinism: 50x identical traces, both engines, both service
kinds, INCLUDING the trip lap count; plus a PYTHONHASHSEED sweep.

A trace is (ordered transitions, lap count, trip-or-not, final context).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

from common2 import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
    emit,
    make_service,
)
from xstate_statemachine.exceptions import RunawayChainError

RUNS = int(next((a.split("=")[1] for a in sys.argv[1:] if a.startswith("--runs=")), 50))

CFG = {
    "id": "r10",
    "initial": "a",
    "context": {"n": 0},
    "maxIterations": 30,
    "states": {
        "a": {
            "invoke": {
                "src": "s",
                "onDone": {"target": "b", "actions": ["act"]},
                "onError": {"target": "b"},
            },
            "on": {"GO": {"target": "z"}},
        },
        "b": {"always": {"target": "a", "actions": ["act"]}},
        "z": {},
    },
}


class Trace(PluginBase):
    def __init__(self) -> None:
        self.t = []

    def on_transition(self, i, f, t, e):  # noqa: ANN001
        self.t.append((getattr(e, "type", "?"), tuple(sorted(n.id for n in t))))


LAPS = {"n": 0}


def act(i, ctx, e, ad):  # noqa: ANN001
    LAPS["n"] += 1
    ctx["n"] = ctx.get("n", 0) + 1


def mk(kind: str):
    return create_machine(
        CFG,
        logic=MachineLogic(actions={"act": act}, services={"s": make_service(kind)}),
    )


async def run_async(kind: str) -> str:
    LAPS["n"] = 0
    tr = Trace()
    i = Interpreter(mk(kind)).use(tr)
    await asyncio.wait_for(i.start(), 10)
    await asyncio.sleep(0.5)
    laps = LAPS["n"]
    trip = isinstance(i.last_error, RunawayChainError)
    ctx = dict(i.context)
    await asyncio.wait_for(i.stop(), 20)
    return json.dumps(
        {"trace": tr.t[:40], "laps": laps, "trip": trip, "n": ctx.get("n")},
        sort_keys=True,
        default=str,
    )


def run_sync(kind: str) -> str:
    if kind == "async def":
        return "N/A"
    LAPS["n"] = 0
    tr = Trace()
    i = SyncInterpreter(mk(kind)).use(tr)
    try:
        i.start()
    except RunawayChainError:
        pass
    laps = LAPS["n"]
    trip = isinstance(i.last_error, RunawayChainError)
    ctx = dict(i.context)
    try:
        i.stop()
    except Exception:  # noqa: BLE001
        pass
    return json.dumps(
        {"trace": tr.t[:40], "laps": laps, "trip": trip, "n": ctx.get("n")},
        sort_keys=True,
        default=str,
    )


async def main() -> int:
    if os.environ.get("R10_CHILD"):
        # hash-seed sweep child: one run of each, print the digests
        out = {
            f"async:{k}": await run_async(k) for k in ("def", "async def")
        }
        out["sync:def"] = run_sync("def")
        print(json.dumps(out))
        return 0

    results = {}
    for kind in ("def", "async def"):
        a = {await run_async(kind) for _ in range(RUNS)}
        results[f"async:{kind}"] = sorted(a)
        s = {run_sync(kind) for _ in range(RUNS)}
        results[f"sync:{kind}"] = sorted(s)

    distinct = {k: len(v) for k, v in results.items()}
    nondet = [k for k, v in distinct.items() if v != 1]

    # laps + trip parity across engines for the `def` kind
    a0 = json.loads(results["async:def"][0])
    s0 = json.loads(results["sync:def"][0])
    parity = {
        "async_laps": a0["laps"],
        "sync_laps": s0["laps"],
        "async_trip": a0["trip"],
        "sync_trip": s0["trip"],
        "laps_equal": a0["laps"] == s0["laps"],
        "trip_equal": a0["trip"] == s0["trip"],
    }

    # --- hash-seed sweep ---
    seeds = ["0", "1", "7", "12345", "99991"]
    sweep = {}
    for sd in seeds:
        env = {**os.environ, "PYTHONHASHSEED": sd, "R10_CHILD": "1",
               "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        p = subprocess.run(
            [sys.executable, os.path.abspath(__file__)],
            capture_output=True, text=True, env=env, timeout=90,
        )
        sweep[sd] = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else f"ERR:{p.stderr[-200:]}"
    distinct_across_seeds = len(set(sweep.values()))

    bad = nondet or not parity["laps_equal"] or not parity["trip_equal"] or (
        distinct_across_seeds != 1
    )
    emit(
        "r10_determinism_and_hashseed",
        {
            "runs_per_cell": RUNS,
            "distinct_traces_per_cell": distinct,
            "nondeterministic_cells": nondet,
            "engine_parity_def": parity,
            "hashseeds": seeds,
            "distinct_outcomes_across_seeds": distinct_across_seeds,
            "sample_trace": results["async:def"][0][:300],
            "result": "FAIL" if bad else "PASS",
        },
    )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
