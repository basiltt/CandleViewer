# -*- coding: utf-8 -*-
"""R6-02 -- the async chain budget exempts EVERY system event
(`interpreter.py:1427`), so an invoke cycle runs unbounded and silent on
`Interpreter` while `SyncInterpreter` trips `RunawayChainError`.

Shape: two states, each with an `invoke` whose `onDone` targets the other.
Every lap is a `done.invoke.*` -- an engine completion -- so the async
exemption means the budget is never charged AT ALL.

Library only, no project machinery. cec108b (unreleased 0.8.1), Python 3.13.

Exit code 1 == the parity break was observed.
"""
import asyncio
import copy
import logging
import time

logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
)

BUDGET_S = 8.0

CFG = {
    "id": "cyc",
    "initial": "idle",
    "maxIterations": 500,
    "states": {
        "idle": {"on": {"GO": "ver"}},
        "ver": {"invoke": {"id": "ver", "src": "svc",
                           "onDone": {"target": "#cyc.arm"}}},
        "arm": {"invoke": {"id": "arm", "src": "svc",
                           "onDone": {"target": "#cyc.ver"}}},
    },
}

laps = []


class Spy:
    """Minimal plugin: record every event the engine drops."""

    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interp, event, reason):
        self.dropped.append((getattr(event, "type", event), reason))

    def __getattr__(self, _name):          # all other hooks are no-ops
        return lambda *a, **k: None


async def svc_async(interp, ctx, evt):
    laps.append(time.monotonic())
    return {"ok": 1}


def svc_sync(interp, ctx, evt):
    laps.append(time.monotonic())
    return {"ok": 1}


def build(sync):
    return create_machine(
        copy.deepcopy(CFG),
        logic=MachineLogic(
            actions={}, guards={},
            services={"svc": svc_sync if sync else svc_async},
        ),
    )


async def async_probe():
    laps.clear()
    spy = Spy()
    it = Interpreter(build(False), strict=False)
    it.use(spy)
    await asyncio.wait_for(it.start(), timeout=BUDGET_S)
    t0 = time.monotonic()
    await it.send("GO")
    while time.monotonic() - t0 < BUDGET_S and it.status == "running":
        await asyncio.sleep(0.25)
    dt = time.monotonic() - t0
    n = len(laps)
    print("async : %d laps in %.2fs (%.0f/s)" % (n, dt, n / dt))
    print("        status=%s  error=%r  last_transition_ok=%s  dropped=%r"
          % (it.status, it.error,
             getattr(it, "last_transition_ok", None), spy.dropped))
    signal = bool(spy.dropped) or it.error is not None
    await it.stop()
    return n, signal


def sync_probe():
    laps.clear()
    spy = Spy()
    it = SyncInterpreter(build(True), strict=False)
    it.use(spy)
    it.start()
    t0 = time.monotonic()
    r = it.send("GO", wait=True)
    dt = time.monotonic() - t0
    n = len(laps)
    err = type(r.error).__name__ if r is not None and r.error else None
    print("sync  : %d laps in %.2fs -> Receipt.error=%s" % (n, dt, err))
    print("        dropped=%r  last_transition_ok=%s"
          % (spy.dropped, getattr(it, "last_transition_ok", None)))
    it.stop()
    return n, bool(spy.dropped) or err is not None


def main():
    s_laps, s_signal = sync_probe()
    a_laps, a_signal = asyncio.run(async_probe())
    print()
    if s_signal and not a_signal:
        print("REPRODUCED: sync charges the budget and signals; async never "
              "charges it (%d async laps vs %d sync)." % (a_laps, s_laps))
        return 1
    print("NOT reproduced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
