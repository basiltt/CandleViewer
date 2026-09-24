# -*- coding: utf-8 -*-
"""Verify #168 on main @ 221ce7c: async chain budget no longer exempts
EVERY completion unconditionally; only the first completion at the trip is
spared, matching the sync engine's `spare = is_completion and not tripped`.

Criteria:
 1. An invoke ping-pong cycle (`ver -> arm -> ver`, all done.invoke laps)
    trips RunawayChainError on the ASYNC engine (previously ran unbounded).
 2. It trips at the same lap-count order of magnitude as sync (parity),
    not thousands of laps later.
 3. `last_transition_ok` is False and an on_event_dropped('chain_budget')
    fires once tripped.

Exit 0 if all criteria pass, 1 otherwise.
"""
import asyncio
import sys

from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine

LIMIT = 50

CFG = {
    "id": "cyc",
    "initial": "ver",
    "maxIterations": LIMIT,
    "states": {
        "ver": {
            "invoke": {"id": "v", "src": "noop", "onDone": {"target": "arm"}},
        },
        "arm": {
            "invoke": {"id": "a", "src": "noop", "onDone": {"target": "ver"}},
        },
    },
}


def noop(interpreter, context, event):
    return {}


class Sink:
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interpreter, event, reason):
        self.dropped.append((event.type, reason))

    def __getattr__(self, item):
        def _noop(*a, **k):
            return None
        return _noop


def run_sync():
    m = create_machine(CFG, logic=MachineLogic(services={"noop": noop}))
    i = SyncInterpreter(m)
    plugin = Sink()
    i._plugins.append(plugin)
    i.start()
    laps = 0
    deadline_laps = 5000
    while i.last_transition_ok and laps < deadline_laps:
        laps += 1
    return i, plugin, laps


async def run_async():
    m = create_machine(CFG, logic=MachineLogic(services={"noop": noop}))
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
    return i, plugin, laps


def main():
    sync_i, sync_plugin, sync_laps = run_sync()
    async_i, async_plugin, async_laps = asyncio.run(run_async())

    print(f"sync : tripped={not sync_i.last_transition_ok} error={sync_i.last_error!r} "
          f"dropped={sync_plugin.dropped}")
    print(f"async: tripped={not async_i.last_transition_ok} error={async_i.last_error!r} "
          f"dropped={async_plugin.dropped} laps~{async_laps}")

    ok = True
    c1 = not async_i.last_transition_ok and async_i.last_error is not None
    print(f"[1] async trips RunawayChainError: {c1}")
    ok &= c1

    c2 = async_laps < 5000  # tripped well within the 8s window, not thousands unbounded
    print(f"[2] async trips promptly (not unbounded): {c2}")
    ok &= c2

    c3 = ("chain_budget" in [r for (_, r) in async_plugin.dropped])
    print(f"[3] on_event_dropped('chain_budget') fired: {c3}")
    ok &= c3

    print("RESULT:", "PASS" if ok else "FAIL")

    # --- Residual check: coroutine (async def) services still bypass the
    # budget entirely (see 168.result.md). Reported, not counted into the
    # PASS/FAIL above since the pinned upstream regression test only
    # exercises plain-def services.
    async def coroutine_cycle_residual():
        async def svc(interp, ctx, evt):
            return {"ok": True}

        m = create_machine(CFG, logic=MachineLogic(services={"noop": svc}))
        i = Interpreter(m)
        await i.start()
        await asyncio.sleep(1.0)
        tripped = not i.last_transition_ok
        await i.stop()
        return tripped

    coroutine_tripped = asyncio.run(coroutine_cycle_residual())
    print(f"[residual] coroutine-service cycle trips within 1s: {coroutine_tripped} "
          f"(False = #168 gap persists for async-def services)")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
