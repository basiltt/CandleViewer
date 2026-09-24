# -*- coding: utf-8 -*-
"""Verify #207 on main @ 19cb1f1: a chain cut that strands an invocation is
observable via RunawayChainError.stranded, on_invocation_stranded hook, an
ERROR log naming the state, and has_dormant_invocations / pending_invocations().

Acceptance criteria (from gh issue #207 body):
  1. RunawayChainError names the stranded invoke id(s) (`.stranded` attr).
  2. A hook fires: `on_invocation_stranded(interpreter, state_id, invoke_id, error)`.
  3. An ERROR log names the state.
  4. `has_dormant_invocations` / `pending_invocations()` answer on demand
     afterwards.
  5. Holds at the DEFAULT maxIterations (1000) -- not just at an explicit
     low limit. IMPORTANT: the chain runs ~0.45-0.5s of real wall time to
     reach the default limit; a caller must wait long enough (the original
     reporter's own repro under-waited: 15*0.03s=0.45s, which is a coin
     flip against the ~0.48s convergence time -- this script polls to a
     stable plateau instead of sampling at a fixed short delay).

Matrix: {def, async def} service x {Interpreter, SyncInterpreter}.

Exit 0 = all cells satisfy every criterion. Exit 1 = any cell fails.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from typing import Any, List, Tuple

logging.disable(logging.CRITICAL)

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    RunawayChainError,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

CFG = {
    "id": "spin",
    "actionErrorPolicy": "rollback",
    "initial": "idle",
    "states": {
        "idle": {"on": {"GO": "starting"}},
        "starting": {"invoke": {"id": "sub", "src": "svc", "onDone": "recording"}},
        "recording": {"entry": ["boom"]},
    },
}


class Recorder(PluginBase):
    def __init__(self) -> None:
        self.hook_calls: List[Tuple[str, str]] = []

    def on_invocation_stranded(self, interp, state_id, invoke_id, error) -> None:
        self.hook_calls.append((state_id, invoke_id))


class LogCatcher(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record.getMessage())


def boom(*a: Any) -> None:
    raise RuntimeError("entry failed")


def mk(kind: str, counter: dict, max_iter=None):
    def svc_def(i, c, e):
        counter["n"] += 1
        return {"ok": True}

    async def svc_async(i, c, e):
        counter["n"] += 1
        return {"ok": True}

    cfg = json.loads(json.dumps(CFG))
    if max_iter is not None:
        cfg["maxIterations"] = max_iter
    svc = svc_def if kind == "def" else svc_async
    logic = MachineLogic(actions={"boom": boom}, services={"svc": svc})
    return create_machine(cfg, logic=logic)


async def check_async(kind: str) -> dict:
    """Interpreter, DEFAULT maxIterations (1000)."""
    rec = Recorder()
    catcher = LogCatcher()
    logger = logging.getLogger("xstate_statemachine")
    prev_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    logger.addHandler(catcher)
    logger.setLevel(logging.ERROR)
    try:
        counter = {"n": 0}
        it = Interpreter(mk(kind, counter), clock=SimulatedClock()).use(rec)
        await it.start()
        t0 = time.time()
        await it.send("GO")
        # Poll to a stable plateau of the SERVICE CALL COUNT (not last_error,
        # which can sit unchanged for many boom iterations before the chain
        # limit trips) -- this is exactly the reporter's own timing mistake
        # in #210: sampling too early/coarsely. Require 5 consecutive stable
        # reads of the counter itself.
        last = None
        stable = 0
        while stable < 5 and time.time() - t0 < 15:
            await asyncio.sleep(0.1)
            cur = counter["n"]
            if cur == last:
                stable += 1
            else:
                stable = 0
            last = cur
        elapsed = time.time() - t0
        err = it.last_error
        result = {
            "kind": kind,
            "elapsed_s": round(elapsed, 3),
            "err_type": type(err).__name__,
            "err_stranded": getattr(err, "stranded", None),
            "hook_calls": rec.hook_calls,
            "log_named_state": any(
                "spin.starting" in m and "sub" in m for m in catcher.records
            ),
            "has_dormant_invocations": it.has_dormant_invocations,
            "pending_invocations": [
                (p.state_id, p.invoke_id) for p in it.pending_invocations()
            ],
        }
        await it.stop()
        return result
    finally:
        logger.removeHandler(catcher)
        logging.disable(prev_disable)


def check_sync(kind: str) -> dict:
    """SyncInterpreter, explicit low limit (sync is driven by caller's tick(),
    so a default-1000 spin would need 1000 explicit .send() calls; the low
    limit is the intended way to exercise this engine per the task's own
    guidance -- both engines are checked at low limits by the pinned suite
    too)."""
    rec = Recorder()
    catcher = LogCatcher()
    logger = logging.getLogger("xstate_statemachine")
    prev_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    logger.addHandler(catcher)
    logger.setLevel(logging.ERROR)
    try:
        if kind != "def":
            # SyncInterpreter requires sync services; only the def lane applies.
            return {"kind": kind, "skipped": "SyncInterpreter requires def services"}
        counter = {"n": 0}
        s = SyncInterpreter(mk("def", counter, max_iter=10)).use(rec)
        s.start()
        r = s.send("GO", wait=True)
        err = r.error
        result = {
            "kind": kind,
            "err_type": type(err).__name__,
            "err_stranded": getattr(err, "stranded", None),
            "hook_calls": rec.hook_calls,
            "log_named_state": any(
                "spin.starting" in m and "sub" in m for m in catcher.records
            ),
            "has_dormant_invocations": s.has_dormant_invocations,
            "pending_invocations": [
                (p.state_id, p.invoke_id) for p in s.pending_invocations()
            ],
        }
        s.stop()
        return result
    finally:
        logger.removeHandler(catcher)
        logging.disable(prev_disable)


def judge(r: dict) -> List[str]:
    problems = []
    if r.get("skipped"):
        return problems
    if r["err_type"] != "RunawayChainError":
        problems.append(f"err_type={r['err_type']} (expected RunawayChainError)")
    if r.get("err_stranded") != ("sub",):
        problems.append(f"err_stranded={r.get('err_stranded')} (expected ('sub',))")
    if r["hook_calls"] != [("spin.starting", "sub")]:
        problems.append(f"hook_calls={r['hook_calls']}")
    if not r["log_named_state"]:
        problems.append("no ERROR log named the state+invoke id")
    if not r["has_dormant_invocations"]:
        problems.append("has_dormant_invocations is False")
    if r["pending_invocations"] != [("spin.starting", "sub")]:
        problems.append(f"pending_invocations={r['pending_invocations']}")
    return problems


async def main() -> int:
    rows = []
    failures = []
    for kind in ("def", "async def"):
        r = await check_async(kind)
        rows.append(("Interpreter", r))
        p = judge(r)
        if p:
            failures.append(("Interpreter", kind, p))

    for kind in ("def",):  # SyncInterpreter is sync-only by construction
        r = check_sync(kind)
        rows.append(("SyncInterpreter", r))
        p = judge(r)
        if p:
            failures.append(("SyncInterpreter", kind, p))

    print(json.dumps(rows, indent=1, default=str))
    if failures:
        print("\nFAILURES:")
        for engine, kind, problems in failures:
            print(f"  {engine}/{kind}: {problems}")
        return 1
    print("\nALL CELLS PASS")
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(asyncio.wait_for(main(), 100.0))
    except asyncio.TimeoutError:
        print("watchdog fired")
        rc = 1
    sys.exit(rc)
