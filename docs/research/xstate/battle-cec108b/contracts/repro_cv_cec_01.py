# -*- coding: utf-8 -*-
"""CV-CEC-01: an event arriving while a plain-`def` service runs is evaluated
against the configuration the machine reaches AFTER the service completes,
so the invoking state's own `on` handler never fires.

#149 moved plain-def services onto a `service_executor` so the event LOOP
keeps turning, but the entering MACROSTEP still awaits the result, so the
machine is unresponsive for the service's whole duration.

Control: the identical machine with an `async def` service handles PING in
`working` as declared.
"""
from __future__ import annotations
import asyncio, json, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

CFG = {
    "id": "p", "initial": "idle", "context": {"trace": []},
    "states": {
        "idle": {"on": {"GO": "working"}},
        "working": {
            "entry": ["mark_entry"],
            "invoke": {"id": "w", "src": "slow",
                       "onDone": {"target": "done", "actions": ["mark_done"]}},
            # PING is DECLARED here and nowhere else.
            "on": {"PING": {"actions": ["mark_ping"]}},
        },
        "done": {},
    },
}


def logic(svc):
    def act(n):
        def f(i, ctx, e, a):
            ctx["trace"].append(n)
        f.__name__ = n
        return f
    return MachineLogic(
        actions={n: act(n) for n in ("mark_entry", "mark_done", "mark_ping")},
        services={"slow": svc}, strict=True)


def plain(interp, ctx, event):
    time.sleep(0.40)
    return {}


async def aio(interp, ctx, event):
    await asyncio.sleep(0.40)
    return {}


async def probe(svc, label):
    m = create_machine(json.loads(json.dumps(CFG)), logic=logic(svc))
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    await i.send("GO")
    await asyncio.sleep(0.05)          # firmly inside `working`
    assert "p.working" in i.current_state_ids, i.current_state_ids
    t0 = time.perf_counter()
    r = await i.send("PING", wait=True)
    dt = time.perf_counter() - t0
    await asyncio.sleep(0.3)
    print("%-10s PING latency=%.3fs receipt.state_ids=%s mark_ping=%s final=%s"
          % (label, dt, sorted(r.state_ids), "mark_ping" in i.context["trace"],
             sorted(i.current_state_ids)))
    await i.stop()
    return "mark_ping" in i.context["trace"], dt


async def main():
    ok_a, dt_a = await probe(aio, "async def")
    ok_p, dt_p = await probe(plain, "plain def")
    print("VERDICT:", "REPRODUCED" if (ok_a and not ok_p) else "not reproduced",
          "| async handled PING in `working`; plain-def did not, and the send "
          "blocked %.2fs (the service's whole duration)." % dt_p)

asyncio.run(main())
