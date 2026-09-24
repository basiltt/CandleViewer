# -*- coding: utf-8 -*-
"""Standalone repro: actionErrorPolicy="rollback" + invoke.onDone into a state
whose entry action raises => unbounded re-invocation of the service.

No project machinery. Library only. cec108b (unreleased 0.8.1).

Shape (B11 RecordingSession, minimised):
    starting --invoke svc--> onDone --> recording
    recording.entry = [boom]          (raises)
    rollback undoes the entry, returning to `starting`
    re-entering `starting` re-arms the invoke, the service runs again, ...

Nothing bounds this: not maxIterations, not the chain budget, not the settle
budget -- because every lap is a *separate* macrostep driven by a genuine
external completion (done.invoke.svc), not a self-generated event.

Expected: a contained failure (error state / RunawayChainError / at worst a
single retry).
Actual:   ~1300 service invocations per second, indefinitely, status="running".
"""
import asyncio, time
from xstate_statemachine import create_machine, MachineLogic, Interpreter

CFG = {
    "id": "spin",
    "actionErrorPolicy": "rollback",
    "initial": "starting",
    "context": {},
    "states": {
        "starting": {
            "invoke": {"id": "s", "src": "svc",
                       "onDone": {"target": "#spin.recording"}}},
        "recording": {"entry": ["boom"]},
    },
}

calls = []


async def svc(interp, ctx, evt):
    calls.append(time.monotonic())
    return {"ok": True}


def boom(interp, ctx, evt, ad):
    raise RuntimeError("entry action failed")


async def main():
    m = create_machine(CFG, logic=MachineLogic(
        actions={"boom": boom}, services={"svc": svc}))
    it = Interpreter(m)
    await it.start()
    for _ in range(4):
        await asyncio.sleep(0.5)
        print("t=%.1fs  service invocations=%-6d  state=%s  status=%s"
              % (time.monotonic() - t0, len(calls),
                 sorted(it.current_state_ids), it.status))
    await it.stop()
    print("\nservice was invoked %d times for ONE user-visible event; "
          "status never left 'running'." % len(calls))


t0 = time.monotonic()
asyncio.run(main())
