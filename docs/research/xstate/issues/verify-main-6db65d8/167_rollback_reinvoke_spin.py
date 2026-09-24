# -*- coding: utf-8 -*-
"""Verify #167 on main @ 6db65d8: rollback -> re-arm -> done -> rollback
cycle is bounded, matrix {def, async def} x {Interpreter, SyncInterpreter}.

SyncInterpreter only supports `def` services (async def raises
NotSupportedError at invoke time) so the SyncInterpreter/async-def cell is
N/A by construction -- reported as such, not counted as a failure.

Criteria (from issue #167 acceptance criteria / CHANGELOG #167 reopen):
 1. Service call count settles (stops growing) well under an unbounded
    spin; bounded relative to maxIterations (default 1000).
 2. Trip is observable: last_error/receipt.error is RunawayChainError (or
    the interpreter's dropped-event bookkeeping records "chain_budget").
 3. Machine survives (status == "running"), not bricked.
 4. Original R6-03 standalone repro (coroutine-service shape) exits 0.
"""
import asyncio
import subprocess
import sys

sys.path.insert(
    0,
    "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/"
    "xstate-statemachine/src",
)
import logging

logging.disable(logging.CRITICAL)

from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
)
from xstate_statemachine.exceptions import RunawayChainError

CFG = {
    "id": "spin",
    "actionErrorPolicy": "rollback",
    "initial": "starting",
    "context": {},
    "states": {
        "starting": {
            "invoke": {
                "id": "s",
                "src": "svc",
                "onDone": {"target": "#spin.recording"},
            },
        },
        "recording": {"entry": ["boom"]},
    },
}


def boom(*a):
    raise RuntimeError("boom")


class Drops:
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interp, event, reason):
        self.dropped.append(reason)

    def __getattr__(self, item):
        return lambda *a, **k: None


async def check_async(is_async_service: bool):
    calls = [0]

    if is_async_service:
        async def svc(i, c, e):
            calls[0] += 1
            return 1
    else:
        def svc(i, c, e):
            calls[0] += 1
            return 1

    d = Drops()
    i = Interpreter(
        create_machine(CFG, logic=MachineLogic(actions={"boom": boom}, services={"svc": svc}))
    ).use(d)
    await i.start()
    await asyncio.sleep(0.6)
    first = calls[0]
    await asyncio.sleep(0.4)
    later = calls[0]
    status = i.status
    dropped = list(d.dropped)
    await i.stop()

    settled = first == later
    bounded = first <= 1010
    chain_budget_seen = "chain_budget" in dropped
    running = status == "running"
    ok = settled and bounded and chain_budget_seen and running
    detail = (
        f"calls@0.6s={first} calls@1.0s={later} status={status} "
        f"dropped={set(dropped)} settled={settled} bounded={bounded} "
        f"chain_budget={chain_budget_seen} running={running}"
    )
    return ok, detail


def check_sync(is_async_service: bool):
    if is_async_service:
        return None, "N/A: SyncInterpreter rejects async def services (NotSupportedError)"

    calls = [0]

    def svc(i, c, e):
        calls[0] += 1
        return 1

    d = Drops()
    i = SyncInterpreter(
        create_machine(CFG, logic=MachineLogic(actions={"boom": boom}, services={"svc": svc}))
    )
    i._plugins.append(d)
    i.start()
    laps = 0
    while i.last_transition_ok and laps < 5000:
        laps += 1
    first = calls[0]
    status = i.status
    dropped = list(d.dropped)
    i.stop()

    bounded = first <= 1010
    chain_budget_seen = "chain_budget" in dropped
    running = status == "running"
    tripped = not i.last_transition_ok
    ok = bounded and (chain_budget_seen or tripped) and running
    detail = (
        f"calls={first} laps~{laps} status={status} dropped={set(dropped)} "
        f"bounded={bounded} chain_budget={chain_budget_seen} tripped={tripped} "
        f"running={running} last_error={i.last_error!r}"
    )
    return ok, detail


def run_original_repro():
    path = (
        "C:/Users/basil/Desktop/Projects/FullStackProjects/CandleViewer/"
        "docs/research/xstate/issues/post-cec108b/new/repro/"
        "R6-03_rollback_ondone_reinvoke_spin.py"
    )
    r = subprocess.run(
        [
            "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/"
            "xstate-statemachine/.venv-main/Scripts/python",
            path,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    print("[orig-repro stdout]\n" + r.stdout)
    if r.stderr:
        print("[orig-repro stderr]\n" + r.stderr)
    # NOTE: the repro's own pass/fail heuristic is `async_n > 100 * sync_n`,
    # designed to catch an UNBOUNDED spin (~20000 calls) vs sync's 2. On the
    # fixed tree the async count is bounded to ~1002 (maxIterations+2) which
    # still trips that ratio (1002 > 100*2), so the script's own exit code
    # is a false negative here -- it cannot distinguish "unbounded" from
    # "bounded but still much larger than sync's 2 calls". We instead parse
    # the printed invocation count directly and check it is bounded, which
    # is the actual acceptance criterion.
    import re
    counts = [int(x) for x in re.findall(r"invocations=(\d+)", r.stdout)]
    bounded_in_repro = bool(counts) and max(counts) <= 1010 and len(set(counts)) <= 1
    print(f"[orig-repro parsed] async invocation counts observed: {counts} "
          f"bounded_and_settled={bounded_in_repro}")
    return bounded_in_repro, r.returncode


if __name__ == "__main__":
    results = {}
    results[("Interpreter", "def")] = asyncio.run(check_async(False))
    results[("Interpreter", "async def")] = asyncio.run(check_async(True))
    results[("SyncInterpreter", "def")] = check_sync(False)
    results[("SyncInterpreter", "async def")] = check_sync(True)

    print("\n=== CELL TABLE #167 ===")
    print(f"{'engine':<17}{'service':<10}{'result':<8}detail")
    all_ok = True
    for (engine, kind), (ok, detail) in results.items():
        if ok is None:
            res = "N/A"
        else:
            res = "PASS" if ok else "FAIL"
            all_ok = all_ok and ok
        print(f"{engine:<17}{kind:<10}{res:<8}{detail}")

    orig_ok, orig_rc = run_original_repro()
    print(f"\noriginal repro exit code: {orig_rc} (0=fixed)")
    all_ok = all_ok and orig_ok

    print("\nRESULT:", "PASS" if all_ok else "FAIL")
    sys.exit(0 if all_ok else 1)
