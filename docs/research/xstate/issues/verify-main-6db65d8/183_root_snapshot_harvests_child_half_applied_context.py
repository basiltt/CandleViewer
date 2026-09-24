# -*- coding: utf-8 -*-
"""Verify #183 on main @ 6db65d8.

Acceptance: parent snapshot taken while a child is mid-step (entry action
writing context) must not harvest a torn child context. Child on caller's
own thread (async child under async parent) => instant SnapshotMidStepError.
Matrix: {def, async def} child action x {Interpreter, SyncInterpreter}.
"""
import asyncio
import threading
import time

from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import SnapshotMidStepError

CHILD = {
    "id": "kid",
    "initial": "x",
    "context": {"q": 100, "p": 0},
    "states": {
        "x": {"on": {"GO": {"target": "y", "actions": ["write"]}}},
        "y": {},
    },
}
PARENT = {
    "id": "p",
    "initial": "up",
    "states": {"up": {"invoke": {"src": "kid", "id": "kid"}}},
}


def sync_write(interp, ctx, ev, action_def):
    time.sleep(0.15)
    ctx["p"] = 101


async def async_write(interp, ctx, ev, action_def):
    await asyncio.sleep(0.15)
    ctx["p"] = 101


def run_async_engine(action_fn) -> str:
    async def main():
        child = create_machine(CHILD, logic=MachineLogic(actions={"write": action_fn}))
        parent = create_machine(PARENT, logic=MachineLogic(services={"kid": child}))
        p = Interpreter(parent)
        await p.start()
        kid = next(iter(p._actors.values()))
        kid.send("GO")
        await asyncio.sleep(0.02)
        try:
            blob = p.get_persisted_snapshot()
            kid_ctx = blob.get("actors", {}).get("p:kid", {}).get("snapshot", {}).get("context")
            result = "ACCEPTED ctx=%r" % (kid_ctx,)
        except SnapshotMidStepError:
            result = "REFUSED"
        try:
            await asyncio.wait_for(p.stop(), timeout=3)
        except Exception:
            pass
        return result

    return asyncio.run(main())


def run_sync_engine(action_fn) -> str:
    child = create_machine(CHILD, logic=MachineLogic(actions={"write": action_fn}))
    parent = create_machine(PARENT, logic=MachineLogic(services={"kid": child}))
    p = SyncInterpreter(parent)
    p.start()
    kid = next(iter(p._actors.values()))
    kid.send("GO")
    time.sleep(0.02)
    try:
        blob = p.get_persisted_snapshot()
        kid_ctx = blob.get("actors", {}).get("p:kid", {}).get("snapshot", {}).get("context")
        result = "ACCEPTED ctx=%r" % (kid_ctx,)
    except SnapshotMidStepError:
        result = "REFUSED"
    p.stop()
    return result


def main() -> int:
    cells = {}
    # async engine, async child action: child on same event loop thread -> instant refusal
    cells[("Interpreter", "async def")] = run_async_engine(async_write)
    # sync engine, sync child action: SyncInterpreter child runs on its own pump thread ->
    # bounded wait then settle, ACCEPTED with settled ctx (not torn)
    cells[("SyncInterpreter", "def")] = run_sync_engine(sync_write)
    # sync engine with async def action is invalid combination for that engine; skip
    # async engine with def (blocking) child action: blocks the loop thread too -> refusal
    cells[("Interpreter", "def")] = run_async_engine(sync_write)

    print("cell table:")
    ok = True
    for k, v in cells.items():
        print("  %-30s %s" % (str(k), v))
        # PASS iff either REFUSED, or ACCEPTED with settled ctx {'p': 101} (not torn {'p': 0})
        if v.startswith("ACCEPTED") and "'p': 0" in v:
            ok = False
    print()
    if ok:
        print("PASS: no torn child context harvested in any cell")
        return 0
    print("FAIL: torn context observed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
