"""s7 (@f28719c) -- STANDALONE re-run of R10 determinism with a SETTLE
parameter, to separate "non-deterministic" from "sampled before the
machine reached rest". R10's 0.5 s window now samples mid-chain on this
build, so it reports 4 distinct traces and a false parity gap.

Run: python s7_determinism_settled.py [--runs=30] [--settle=3.0]
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import RunawayChainError


def arg(name: str, default):  # noqa: ANN001
    for a in sys.argv[1:]:
        if a.startswith(f"--{name}="):
            return type(default)(a.split("=", 1)[1])
    return default


RUNS = arg("runs", 30)
SETTLE = arg("settle", 3.0)


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def make_service(kind: str):
    if kind == "def":

        def svc(i, ctx, e):  # noqa: ANN001
            return {"v": 1}

        return svc

    async def asvc(i, ctx, e):  # noqa: ANN001
        return {"v": 1}

    return asvc


CFG = {
    "id": "s7",
    "initial": "a",
    "context": {"n": 0},
    "maxIterations": 30,
    "states": {
        "a": {
            "invoke": {"src": "s", "onDone": {"target": "b", "actions": ["act"]},
                       "onError": {"target": "b"}},
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
        json.loads(json.dumps(CFG)),
        logic=MachineLogic(actions={"act": act}, services={"s": make_service(kind)}),
    )


async def run_async(kind: str, settle: float) -> str:
    LAPS["n"] = 0
    tr = Trace()
    i = Interpreter(mk(kind)).use(tr)
    await asyncio.wait_for(i.start(), 10)
    await asyncio.sleep(settle)
    laps = LAPS["n"]
    trip = isinstance(i.last_error, RunawayChainError)
    ctx = dict(i.context)
    await asyncio.wait_for(i.stop(), 20)
    return json.dumps({"trace": tr.t[:40], "laps": laps, "trip": trip,
                       "n": ctx.get("n")}, sort_keys=True, default=str)


def run_sync(kind: str) -> str:
    if kind == "async def":
        return "N/A"
    LAPS["n"] = 0
    tr = Trace()
    i = SyncInterpreter(mk(kind)).use(tr)
    i.start()
    laps = LAPS["n"]
    trip = isinstance(i.last_error, RunawayChainError)
    ctx = dict(i.context)
    i.stop()
    return json.dumps({"trace": tr.t[:40], "laps": laps, "trip": trip,
                       "n": ctx.get("n")}, sort_keys=True, default=str)


async def main() -> int:
    cells: Dict[str, set] = {}
    lat: Dict[str, Any] = {}
    for kind in ("def", "async def"):
        s = set()
        for _ in range(RUNS):
            s.add(await run_async(kind, SETTLE))
        cells[f"async:{kind}"] = s
        lat[f"async:{kind}"] = json.loads(next(iter(s)))["laps"]
        s2 = set()
        for _ in range(RUNS):
            s2.add(run_sync(kind))
        cells[f"sync:{kind}"] = s2
        if kind == "def":
            lat[f"sync:{kind}"] = json.loads(next(iter(s2)))["laps"]

    # time-to-rest measurement: how long until laps stops moving
    LAPS["n"] = 0
    i = Interpreter(mk("def"))
    await i.start()
    t0 = time.monotonic()
    prev, rest_at = -1, None
    for _ in range(300):
        await asyncio.sleep(0.02)
        if LAPS["n"] == prev and LAPS["n"] > 0:
            rest_at = round(time.monotonic() - t0, 3)
            break
        prev = LAPS["n"]
    await i.stop()

    nondet = [k for k, v in cells.items() if len(v) != 1]
    parity = {
        "async_laps": lat.get("async:def"),
        "sync_laps": lat.get("sync:def"),
        "laps_equal": lat.get("async:def") == lat.get("sync:def"),
    }
    emit("s7_determinism_settled",
         {"runs_per_cell": RUNS, "settle_seconds": SETTLE,
          "distinct_traces_per_cell": {k: len(v) for k, v in cells.items()},
          "nondeterministic_cells": nondet,
          "time_to_rest_seconds_def": rest_at,
          "engine_parity_def": parity,
          "result": "PASS" if not nondet and parity["laps_equal"] else "FAIL"})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
