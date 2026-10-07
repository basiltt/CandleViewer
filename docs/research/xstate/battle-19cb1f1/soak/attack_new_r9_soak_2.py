# -*- coding: utf-8 -*-
"""Round-9 soak attacks, part 2: stranded-invocation hook under concurrent
storm (#207) and delayed self-send debt / maxIterations bound (#206).

Standalone; both engines where relevant.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from typing import Any, Dict, List

sys.path.insert(0, "<workspace>/_ref/xstate-statemachine/src")

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    RunawayChainError,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.plugins import PluginBase  # noqa: E402

MAX_ITER = 15

# rollback + invoke.onDone storm: the service completes fast, but the state
# reached on onDone re-raises on entry, forcing a rollback loop; cut at
# maxIterations should strand the invocation and fire the hook exactly once
# (mirrors tests/test_round9_findings.py::TestStrandedInvocationObservable).
CFG_C = {
    "id": "spin",
    "actionErrorPolicy": "rollback",
    "initial": "idle",
    "maxIterations": MAX_ITER,
    "states": {
        "idle": {"on": {"GO": "starting"}},
        "starting": {
            "invoke": {"id": "sub", "src": "svc", "onDone": "recording"},
        },
        "recording": {"entry": ["boom"]},
    },
}


def svc_def(i, c, e):  # noqa: ANN001
    return 1


async def svc_async(i, c, e):  # noqa: ANN001
    await asyncio.sleep(0)
    return 1


def boom(*a: Any) -> None:  # noqa: ANN001
    raise RuntimeError("entry failed (intentional, rollback-policy)")


class Drops(PluginBase):
    def __init__(self) -> None:
        self.stranded: List[Any] = []
        self.errors: List[str] = []

    def on_invocation_stranded(self, interp, state_id, invoke_id, error) -> None:  # noqa: ANN001
        self.stranded.append((state_id, invoke_id))

    def on_error(self, interp, error) -> None:  # noqa: ANN001
        self.errors.append(repr(error))


async def one_async_storm(idx: int) -> Dict[str, Any]:
    logic = MachineLogic(actions={"boom": boom}, services={"svc": svc_async})
    m = create_machine(dict(CFG_C), logic=logic)
    plug = Drops()
    interp = Interpreter(m)
    interp.use(plug)
    await interp.start()
    raised: Any = None
    try:
        await interp.send({"type": "GO"})
    except RunawayChainError as exc:
        raised = exc
    for _ in range(100):
        await asyncio.sleep(0.05)
        if interp.last_error is not None:
            break
    dormant = interp.has_dormant_invocations if hasattr(interp, "has_dormant_invocations") else None
    await interp.stop()
    return {
        "idx": idx,
        "raised_stranded": getattr(raised, "stranded", None) if raised else None,
        "last_error_stranded": getattr(interp.last_error, "stranded", None),
        "hook_fires": len(plug.stranded),
        "dormant": dormant,
    }


def one_sync_storm(idx: int) -> Dict[str, Any]:
    logic = MachineLogic(actions={"boom": boom}, services={"svc": svc_def})
    m = create_machine(dict(CFG_C), logic=logic)
    plug = Drops()
    interp = SyncInterpreter(m)
    interp.use(plug)
    interp.start()
    r = interp.send("GO", wait=True)
    dormant = interp.has_dormant_invocations if hasattr(interp, "has_dormant_invocations") else None
    interp.stop()
    return {
        "idx": idx,
        "raised_stranded": getattr(r.error, "stranded", None),
        "hook_fires": len(plug.stranded),
        "dormant": dormant,
    }


async def run_c(n: int = 20) -> Dict[str, Any]:
    results = await asyncio.gather(*[one_async_storm(i) for i in range(n)])
    sync_results = [one_sync_storm(i) for i in range(n)]
    async_ok = all(r["hook_fires"] == 1 and r["last_error_stranded"] for r in results)  # noqa: E501
    sync_ok = all(r["hook_fires"] == 1 and r["raised_stranded"] for r in sync_results)
    return {
        "n": n,
        "async_ok_exactly_once": async_ok,
        "sync_ok_exactly_once": sync_ok,
        "async_sample": results[:2],
        "sync_sample": sync_results[:2],
    }


# ---------------------------------------------------------------------------
# B. delayed self-send (raise(delay=)) ping-pong trips maxIterations, both
#    engines, same lap (+-1) -- charged as engine work per #206.
# ---------------------------------------------------------------------------
CFG_B = {
    "id": "m",
    "initial": "a",
    "maxIterations": 20,
    "context": {"n": 0},
    "states": {
        "a": {
            "entry": [{"type": "raise", "params": {"event": "GO", "delay": 1}}],
            "on": {"GO": "b"},
            "exit": ["tick"],
        },
        "b": {
            "entry": [{"type": "raise", "params": {"event": "GO", "delay": 1}}],
            "on": {"GO": "a"},
            "exit": ["tick"],
        },
    },
}


def tick(i, c, e, a):  # noqa: ANN001
    c["n"] = c.get("n", 0) + 1


async def _plateau(getter, settle_polls: int = 10, interval: float = 0.05) -> int:
    last = -1
    stable = 0
    for _ in range(200):
        await asyncio.sleep(interval)
        cur = getter()
        if cur == last:
            stable += 1
            if stable >= settle_polls:
                return cur
        else:
            stable = 0
        last = cur
    return last


async def run_b_async() -> Dict[str, Any]:
    logic = MachineLogic(actions={"tick": tick})
    m = create_machine(dict(CFG_B), logic=logic)
    interp = Interpreter(m)
    await interp.start()
    n = await _plateau(lambda: interp.context["n"])
    err = interp.last_error
    await interp.stop()
    return {"lap": n, "last_error": type(err).__name__ if err else None}


def run_b_sync() -> Dict[str, Any]:
    clock_free_cfg = dict(CFG_B)
    logic = MachineLogic(actions={"tick": tick})
    m = create_machine(dict(CFG_B), logic=logic)
    interp = SyncInterpreter(m)
    interp.start()
    for _ in range(500):
        interp.tick()
        if interp.last_error is not None:
            break
    err = interp.last_error
    return {"lap": interp.context["n"], "last_error": type(err).__name__ if err else None}


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    t0 = time.time()
    print("=== C: stranded-invocation hook under 20-way concurrent storm, both engines ===")
    c = asyncio.run(run_c(20))
    for k, v in c.items():
        print(k, "=", v)

    print()
    print("=== B: delayed self-send (raise delay=1ms) trips maxIterations, both engines ===")
    b_async = asyncio.run(run_b_async())
    b_sync = run_b_sync()
    print("async:", b_async)
    print("sync:", b_sync)

    print(f"\ndt_s={time.time()-t0:.2f}")
