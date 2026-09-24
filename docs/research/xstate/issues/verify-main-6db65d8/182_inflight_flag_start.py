# -*- coding: utf-8 -*-
"""Verify #182 on main @ 6db65d8: the in-flight flag covers start()'s
initial descent and every on_action_execute hook, on both engines, both
action kinds -- get_persisted_snapshot() from within is refused.
"""
import asyncio
import copy
import logging

logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, PluginBase, create_machine
from xstate_statemachine.exceptions import SnapshotMidStepError

CFG = {
    "id": "oms", "initial": "filled", "context": {"filled_qty": 0, "avg_px": 0},
    "states": {"filled": {"entry": ["set_qty", "set_px"]}},
}


def logic(coro):
    if coro:
        async def set_qty(interp, ctx, evt, ad):
            ctx["filled_qty"] = 100

        async def set_px(interp, ctx, evt, ad):
            ctx["avg_px"] = 101.5
    else:
        def set_qty(interp, ctx, evt, ad):
            ctx["filled_qty"] = 100

        def set_px(interp, ctx, evt, ad):
            ctx["avg_px"] = 101.5
    return MachineLogic(actions={"set_qty": set_qty, "set_px": set_px})


def build(coro):
    return create_machine(copy.deepcopy(CFG), logic=logic(coro))


class Snapper(PluginBase):
    def __init__(self):
        self.rows = []

    def on_action_execute(self, interp, action):
        try:
            interp.get_persisted_snapshot()
            self.rows.append("ACCEPTED")
        except SnapshotMidStepError:
            self.rows.append("REFUSED")


async def cell_async(coro):
    plug = Snapper()
    it = Interpreter(build(coro)).use(plug)
    await it.start()
    await it.stop()
    ok = len(plug.rows) >= 2 and all(r == "REFUSED" for r in plug.rows)
    return ok, plug.rows


def cell_sync(coro):
    plug = Snapper()
    it = SyncInterpreter(build(coro)).use(plug)
    it.start()
    it.stop()
    ok = len(plug.rows) >= 2 and all(r == "REFUSED" for r in plug.rows)
    return ok, plug.rows


async def main():
    results = {}
    for coro in (False, True):
        ok, rows = await cell_async(coro)
        results[("Interpreter", "def" if not coro else "async def")] = (ok, rows)
    for coro in (False,):
        ok, rows = cell_sync(coro)
        results[("SyncInterpreter", "def")] = (ok, rows)
    results[("SyncInterpreter", "async def")] = ("N/A (sync actions are always sync)", [])

    print("%-16s %-12s %-6s %s" % ("Engine", "Kind", "Pass", "rows"))
    all_pass = True
    for (engine, kind), (ok, rows) in results.items():
        print("%-16s %-12s %-6s %s" % (engine, kind, ok, rows))
        if ok is False:
            all_pass = False
    print()
    print("ALL PASS" if all_pass else "FAILURE")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
