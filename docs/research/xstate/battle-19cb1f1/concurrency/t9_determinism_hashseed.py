"""t9 (@19cb1f1) -- STANDALONE determinism. 50 identical runs per cell,
both engines, both service kinds, over the round-10 shapes: an
always+invoke chain, a rollback+onDone storm that strands (#207), and a
delayed self-send ping-pong (#206).

A trace is the ordered list of (entered state, action name) plus the
final error class and lap count. All 50 runs of a cell must produce ONE
distinct trace. Repeated under 3 PYTHONHASHSEED values via a re-exec, so
dict/set iteration order cannot be what is holding it together.

Run: python t9_determinism_hashseed.py [--runs=50]   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import logging
import subprocess
import sys
from collections import Counter
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)


def arg(name: str, default: int) -> int:
    for a in sys.argv[1:]:
        if a.startswith("--" + name + "="):
            return int(a.split("=")[1])
    return default


# The rollback shape logs a full traceback per lap; that is expected
# noise, not the observation, and it swamps stdout.
logging.getLogger("xstate_statemachine").setLevel(logging.CRITICAL)
logging.disable(logging.ERROR)

RUNS = arg("runs", 50)
CHILD = "--child" in sys.argv


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


INV = {"id": "s", "src": "svc", "onDone": {"target": "b"}}

SHAPES: Dict[str, Dict[str, Any]] = {
    "always_invoke": {
        "id": "d", "initial": "a", "maxIterations": 8, "context": {},
        "states": {
            "a": {"entry": ["tick"], "invoke": dict(INV)},
            "b": {"entry": ["tick"], "always": {"target": "a"}},
        },
    },
    "rollback_strands": {
        "id": "d", "initial": "a", "maxIterations": 8,
        "actionErrorPolicy": "rollback", "context": {},
        "states": {
            "a": {"entry": ["tick"], "invoke": dict(INV)},
            "b": {"entry": ["tick", "boom"]},
        },
    },
    "delayed_pingpong": {
        "id": "d", "initial": "a", "maxIterations": 8, "context": {},
        "states": {
            "a": {"entry": ["tick",
                            {"type": "raise",
                             "params": {"event": "P", "delay": 0.001}}],
                  "on": {"P": "b"}},
            "b": {"entry": ["tick",
                            {"type": "raise",
                             "params": {"event": "P", "delay": 0.001}}],
                  "on": {"P": "a"}},
        },
    },
}


def build(kind: str, trace: List[str]) -> MachineLogic:
    def tick(i, c, e, ad):  # noqa: ANN001
        trace.append("tick")

    def boom(i, c, e, ad):  # noqa: ANN001
        trace.append("boom")
        raise RuntimeError("boom")

    if kind == "def":

        def svc(i, c, e):  # noqa: ANN001
            trace.append("svc")
            return 1

    else:

        async def svc(i, c, e):  # noqa: ANN001
            trace.append("svc")
            return 1

    return MachineLogic(actions={"tick": tick, "boom": boom},
                        services={"svc": svc})


def digest(trace: List[str], err: str, state: List[str]) -> str:
    blob = "|".join(trace) + "#" + err + "#" + ",".join(state)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


async def run_async(name: str, kind: str) -> str:
    trace: List[str] = []
    itp = Interpreter(
        create_machine(copy.deepcopy(SHAPES[name]), logic=build(kind, trace))
    )
    try:
        await itp.start()
        await asyncio.sleep(0.5)
        err = type(getattr(itp, "last_error", None)).__name__
        state = sorted(itp.current_state_ids)
    except Exception as exc:  # noqa: BLE001
        err, state = type(exc).__name__, []
    finally:
        try:
            await itp.stop()
        except Exception:  # noqa: BLE001
            pass
    return digest(trace, err, state)


def run_sync(name: str, kind: str) -> str:
    trace: List[str] = []
    itp = SyncInterpreter(
        create_machine(copy.deepcopy(SHAPES[name]), logic=build(kind, trace))
    )
    try:
        itp.start()
        err = type(getattr(itp, "last_error", None)).__name__
        state = sorted(itp.current_state_ids)
    except Exception as exc:  # noqa: BLE001
        err, state = type(exc).__name__, []
    finally:
        try:
            itp.stop()
        except Exception:  # noqa: BLE001
            pass
    return digest(trace, err, state)


async def sweep() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    for name in SHAPES:
        for kind in ("def", "async def"):
            ca: Counter = Counter()
            for _ in range(RUNS):
                ca[await run_async(name, kind)] += 1
            cells["async/" + name + "/" + kind] = dict(ca)
            if kind == "def":
                cs: Counter = Counter()
                for _ in range(RUNS):
                    cs[run_sync(name, kind)] += 1
                cells["sync/" + name + "/" + kind] = dict(cs)
    return cells


async def main() -> int:
    cells = await sweep()
    if CHILD:
        print("CHILD_RESULT " + json.dumps(cells))
        return 0

    # Re-exec under 3 hash seeds so dict/set ordering is not the reason.
    seeds: Dict[str, Any] = {}
    for hs in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=hs,
                   PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        try:
            p = subprocess.run(
                [sys.executable, os.path.abspath(__file__), "--child",
                 "--runs=" + str(max(8, RUNS // 5))],
                env=env, capture_output=True, text=True, timeout=100,
            )
            line = [ln for ln in p.stdout.splitlines()
                    if ln.startswith("CHILD_RESULT ")]
            seeds[hs] = json.loads(line[0][13:]) if line else {
                "error": p.stderr[-300:]
            }
        except Exception as exc:  # noqa: BLE001
            seeds[hs] = {"error": type(exc).__name__}

    viol: List[Any] = []
    for key, hist in cells.items():
        if len(hist) != 1:
            viol.append((key, "non-deterministic in-process", hist))
    # cross-seed: the SAME cell must land on the same single digest
    for key in cells:
        got = {hs: list((s.get(key) or {}).keys())
               for hs, s in seeds.items() if "error" not in s}
        flat = {d for v in got.values() for d in v}
        if len(flat) > 1:
            viol.append((key, "digest varies across PYTHONHASHSEED", got))

    emit("t9_determinism_hashseed",
         {"claim": "50x identical traces per cell, both engines, both kinds, "
                   "stable across PYTHONHASHSEED",
          "runs_per_cell": RUNS, "cells": cells,
          "hashseed_children": seeds,
          "violations": viol[:10], "n_violations": len(viol),
          "result": "FAIL" if viol else "PASS"})
    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
