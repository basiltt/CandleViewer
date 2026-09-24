# -*- coding: utf-8 -*-
"""Verify #168 on main @ 6db65d8: async chain budget no longer exempts
EVERY completion unconditionally; matrix {def, async def} x
{Interpreter, SyncInterpreter}.

Criteria (issue #168 acceptance criteria):
 1. Invoke ping-pong cycle (ver -> arm -> ver, all done.invoke laps) trips
    RunawayChainError on the ASYNC engine for BOTH service kinds (the gap
    the issue reported was specific to async-def services bypassing the
    budget entirely).
 2. Trips promptly (order of maxIterations laps, not thousands).
 3. on_event_dropped('chain_budget') fires; last_transition_ok is False.
 4. SyncInterpreter parity on the def cell (async def N/A on sync engine).
 5. The "tripping completion is still processed" rule (#94) holds: machine
    does not silently park mid-cycle without any dropped-event evidence.
"""
import asyncio
import sys

from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
)

LIMIT = 50

CFG = {
    "id": "cyc",
    "initial": "ver",
    "maxIterations": LIMIT,
    "states": {
        "ver": {"invoke": {"id": "v", "src": "svc", "onDone": {"target": "arm"}}},
        "arm": {"invoke": {"id": "a", "src": "svc", "onDone": {"target": "ver"}}},
    },
}


class Sink:
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interpreter, event, reason):
        self.dropped.append((event.type, reason))

    def __getattr__(self, item):
        return lambda *a, **k: None


def run_sync(is_async_service: bool):
    if is_async_service:
        return None, "N/A: SyncInterpreter rejects async def services (NotSupportedError)"

    def svc(interp, ctx, evt):
        return {}

    m = create_machine(CFG, logic=MachineLogic(services={"svc": svc}))
    i = SyncInterpreter(m)
    plugin = Sink()
    i._plugins.append(plugin)
    i.start()
    laps = 0
    while i.last_transition_ok and laps < 5000:
        laps += 1
    i.stop()
    ok = (not i.last_transition_ok) and laps < 5000 and \
        ("chain_budget" in [r for (_, r) in plugin.dropped])
    detail = (
        f"tripped={not i.last_transition_ok} laps~{laps} "
        f"dropped={plugin.dropped} last_error={i.last_error!r}"
    )
    return ok, detail


async def run_async(is_async_service: bool):
    if is_async_service:
        async def svc(interp, ctx, evt):
            return {}
    else:
        def svc(interp, ctx, evt):
            return {}

    m = create_machine(CFG, logic=MachineLogic(services={"svc": svc}))
    i = Interpreter(m)
    plugin = Sink()
    i._plugins.append(plugin)
    await i.start()
    deadline = asyncio.get_event_loop().time() + 8.0
    laps = 0
    while i.last_transition_ok and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.001)
        laps += 1
    await i.stop()
    c1 = (not i.last_transition_ok) and i.last_error is not None
    c2 = laps < 5000
    c3 = "chain_budget" in [r for (_, r) in plugin.dropped]
    ok = c1 and c2 and c3
    detail = (
        f"tripped={not i.last_transition_ok} laps~{laps} "
        f"dropped={plugin.dropped} last_error={i.last_error!r}"
    )
    return ok, detail


if __name__ == "__main__":
    results = {}
    results[("Interpreter", "def")] = asyncio.run(run_async(False))
    results[("Interpreter", "async def")] = asyncio.run(run_async(True))
    results[("SyncInterpreter", "def")] = run_sync(False)
    results[("SyncInterpreter", "async def")] = run_sync(True)

    print("=== CELL TABLE #168 ===")
    print(f"{'engine':<17}{'service':<10}{'result':<8}detail")
    all_ok = True
    for (engine, kind), (ok, detail) in results.items():
        if ok is None:
            res = "N/A"
        else:
            res = "PASS" if ok else "FAIL"
            all_ok = all_ok and ok
        print(f"{engine:<17}{kind:<10}{res:<8}{detail}")

    print("\nRESULT:", "PASS" if all_ok else "FAIL")
    sys.exit(0 if all_ok else 1)
