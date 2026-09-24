# -*- coding: utf-8 -*-
"""Verify #180 on main @ 6db65d8: external send(priority=True) is never
charged to chain budget. Matrix: {def, async def} action x {Interpreter,
SyncInterpreter}. Exit 0 iff all cells pass (zero chain_budget drops).
"""
import asyncio
import copy
import logging

logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, PluginBase, create_machine

N_SENDS = 300
MAX_ITER = 25
CFG = {
    "id": "ext", "maxIterations": MAX_ITER, "initial": "up", "context": {"n": 0},
    "states": {"up": {"on": {"TICK": {"actions": ["work"]}}}},
}


def make_logic(coro, processed):
    if coro:
        async def work(interp, ctx, evt, ad):
            processed.append(1)
            await asyncio.sleep(0.0005)
        return MachineLogic(actions={"work": work})
    else:
        def work(interp, ctx, evt, ad):
            processed.append(1)
        return MachineLogic(actions={"work": work})


async def run_async(coro):
    processed, dropped = [], []
    it = Interpreter(create_machine(copy.deepcopy(CFG), logic=make_logic(coro, processed)))

    class Spy(PluginBase):
        def on_event_dropped(self, interpreter, event, reason):
            dropped.append(reason)

    it.use(Spy())
    await it.start()
    for _ in range(N_SENDS):
        it.send("TICK", priority=True)
        await asyncio.sleep(0.0001)
    await asyncio.sleep(1.0)
    n_drop_budget = sum(1 for r in dropped if r == "chain_budget")
    await it.stop()
    return n_drop_budget == 0, n_drop_budget


def run_sync(coro):
    # SyncInterpreter processes synchronously; use def action only
    processed, dropped = [], []
    it = SyncInterpreter(create_machine(copy.deepcopy(CFG), logic=make_logic(False, processed)))

    class Spy(PluginBase):
        def on_event_dropped(self, interpreter, event, reason):
            dropped.append(reason)

    it.use(Spy())
    it.start()
    for _ in range(N_SENDS):
        it.send("TICK", priority=True)
    n_drop_budget = sum(1 for r in dropped if r == "chain_budget")
    it.stop()
    return n_drop_budget == 0, n_drop_budget


async def main():
    results = {}
    ok, n = await run_async(False)
    results[("Interpreter", "def")] = (ok, n)
    ok, n = await run_async(True)
    results[("Interpreter", "async def")] = (ok, n)
    ok, n = run_sync(False)
    results[("SyncInterpreter", "def")] = (ok, n)
    results[("SyncInterpreter", "async def")] = ("N/A (sync has no coroutine services)", "")

    print("%-16s %-12s %-6s %s" % ("Engine", "Kind", "Pass", "dropped(chain_budget)"))
    all_pass = True
    for (engine, kind), (ok, n) in results.items():
        print("%-16s %-12s %-6s %s" % (engine, kind, ok, n))
        if ok is False:
            all_pass = False
    print()
    print("ALL PASS" if all_pass else "FAILURE")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
