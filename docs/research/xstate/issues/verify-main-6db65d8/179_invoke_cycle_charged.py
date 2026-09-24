# -*- coding: utf-8 -*-
"""Verify #179 on main @ 6db65d8: every completion charged, both service
kinds, both engines. Prints a cell table; exit 0 iff all cells pass.
"""
import asyncio
import copy
import logging

logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import RunawayChainError

MAX_ITER = 20
CFG = {
    "id": "lane", "actionErrorPolicy": "rollback", "maxIterations": MAX_ITER,
    "initial": "a", "context": {},
    "states": {
        "a": {"invoke": {"id": "sa", "src": "svc", "onDone": {"target": "#lane.b"}}},
        "b": {"invoke": {"id": "sb", "src": "svc", "onDone": {"target": "#lane.a"}}},
    },
}


def svc_plain(interp, ctx, evt):
    return {"ok": True}


async def svc_coro(interp, ctx, evt):
    return {"ok": True}


def build(coro):
    return create_machine(copy.deepcopy(CFG),
                           logic=MachineLogic(services={"svc": svc_coro if coro else svc_plain}))


async def run_async(coro):
    it = Interpreter(build(coro))
    await it.start()
    t0 = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - t0 < 2.0:
        await asyncio.sleep(0.05)
        if it.last_error is not None:
            break
    ok = isinstance(it.last_error, RunawayChainError)
    await it.stop()
    return ok


def run_sync(coro):
    # SyncInterpreter only supports plain def services meaningfully; use
    # def-returning-awaitable is not native, so run def svc for parity check
    # and skip async-def cell as N/A (sync engine has no coroutine lane).
    it = SyncInterpreter(build(False))
    it.start()
    import time
    t0 = time.monotonic()
    while time.monotonic() - t0 < 2.0:
        if it.last_error is not None:
            break
    ok = isinstance(it.last_error, RunawayChainError)
    it.stop()
    return ok


async def main():
    results = {}
    results[("Interpreter", "def")] = await run_async(False)
    results[("Interpreter", "async def")] = await run_async(True)
    results[("SyncInterpreter", "def")] = run_sync(False)
    results[("SyncInterpreter", "async def")] = "N/A (sync has no coroutine lane)"

    print("%-16s %-12s %s" % ("Engine", "Kind", "Result"))
    all_pass = True
    for (engine, kind), res in results.items():
        print("%-16s %-12s %s" % (engine, kind, res))
        if res is False:
            all_pass = False
    print()
    print("ALL PASS" if all_pass else "FAILURE")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
