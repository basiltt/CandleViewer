# -*- coding: utf-8 -*-
"""R6-03 -- `actionErrorPolicy: "rollback"` + `invoke.onDone` re-arms the invoke
for ever.

Shape (minimised):
    starting --invoke svc--> onDone --> recording
    recording.entry = [boom]          (raises)
    rollback undoes the entry, returning to `starting`
    re-entering `starting` re-arms the invoke, the service runs again, ...

Nothing bounds this: not maxIterations, not the chain budget, not the settle
budget -- because every lap is a *separate* macrostep driven by a genuine
engine completion (`done.invoke.svc`), which `interpreter.py:1427` exempts
from the chain budget unconditionally.

SyncInterpreter on the identical machine is quiescent after 2 invocations.

Library only, no project machinery. cec108b (unreleased 0.8.1), Python 3.13.

Exit code 1 == the unbounded async re-arm was observed.
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

CFG = {
    "id": "spin",
    "actionErrorPolicy": "rollback",
    "initial": "starting",
    "context": {},
    "states": {
        "starting": {
            "invoke": {"id": "s", "src": "svc",
                       "onDone": {"target": "#spin.recording"}},
        },
        "recording": {"entry": ["boom"]},
    },
}

calls = []


async def svc_async(interp, ctx, evt):
    calls.append(time.monotonic())
    return {"ok": True}


def svc_sync(interp, ctx, evt):
    calls.append(time.monotonic())
    return {"ok": True}


def boom(interp, ctx, evt, ad):
    raise RuntimeError("entry action failed")


def build(sync):
    return create_machine(
        copy.deepcopy(CFG),
        logic=MachineLogic(
            actions={"boom": boom},
            services={"svc": svc_sync if sync else svc_async},
        ),
    )


async def async_probe():
    calls.clear()
    it = Interpreter(build(False))
    await it.start()
    t0 = time.monotonic()
    for _ in range(4):
        await asyncio.sleep(0.5)
        print("async : t=%.1fs  service invocations=%-6d  state=%s  status=%s"
              % (time.monotonic() - t0, len(calls),
                 sorted(it.current_state_ids), it.status))
    n = len(calls)
    print("        status=%s  .error=%r  last_transition_ok=%s"
          % (it.status, it.error, getattr(it, "last_transition_ok", None)))
    await it.stop()
    return n


def sync_probe():
    calls.clear()
    it = SyncInterpreter(build(True))
    it.start()
    time.sleep(0.5)
    n = len(calls)
    print("sync  : %d service invocations, state=%s status=%s"
          % (n, sorted(it.current_state_ids), it.status))
    it.stop()
    return n


def main():
    s_n = sync_probe()
    a_n = asyncio.run(async_probe())
    print()
    if a_n > 100 * max(s_n, 1):
        print("REPRODUCED: async %d invocations in 2.0s for ONE user-visible "
              "event; sync %d then quiescent." % (a_n, s_n))
        return 1
    print("NOT reproduced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
