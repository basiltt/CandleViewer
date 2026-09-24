# -*- coding: utf-8 -*-
"""B8: SL_DEADLINE declared IN `attaching` must pre-empt the in-flight
attach invoke and enter `naked`. Minimal machine, no catalogue JSON."""
import asyncio, json
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

CFG = {
    "id": "p", "initial": "flat",
    "actionErrorPolicy": "fail", "onUnhandled": "defer",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "context": {},
    "states": {
        "flat": {"on": {"OPEN": {"target": "#p.attaching"}}},
        "attaching": {
            "entry": ["mark_attaching"],
            "invoke": {"id": "att", "src": "attach",
                       "onDone": {"target": "#p.verifying"},
                       "onError": {"target": "#p.naked"}},
            "on": {"SL_DEADLINE": {"target": "#p.naked"}},
        },
        "verifying": {"entry": ["mark_verifying"]},
        "naked": {"entry": ["mark_naked"]},
    },
}

async def run(release_gate: bool):
    gate = asyncio.Event()
    trace = []
    def act(n):
        def f(i, c, e, a): trace.append(n)
        f.__name__ = n; return f
    async def attach(i, c, e):
        trace.append("svc:attach:start")
        await gate.wait()
        trace.append("svc:attach:done")
        return {"ok": True}
    m = create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic(
        actions={n: act(n) for n in ("mark_attaching","mark_verifying","mark_naked")},
        services={"attach": attach}, strict=True), strict_targets=True)
    it = Interpreter(m, clock=SimulatedClock())
    await it.start(); await asyncio.sleep(0.03)
    r0 = await it.send("OPEN", wait=True); await asyncio.sleep(0.05)
    mid = sorted(it.current_state_ids)
    r = await it.send("SL_DEADLINE", wait=True)
    await asyncio.sleep(0.05)
    after = sorted(it.current_state_ids)
    if release_gate:
        gate.set(); await asyncio.sleep(0.08)
    final = sorted(it.current_state_ids)
    out = {"mid": mid, "receipt": {"changed": r.changed, "deferred": r.deferred,
           "denied": r.denied, "error": type(r.error).__name__ if r.error else None},
           "after_deadline": after, "final": final, "trace": trace,
           "status": it.status, "deferred_count": it.deferred_count}
    await it.stop()
    return out

async def main():
    res = {"gate_never_released": await run(False),
           "gate_released_after": await run(True)}
    print(json.dumps(res, indent=1))
    json.dump(res, open("repro/f1_sl_deadline_preempt.json","w"), indent=1)

asyncio.run(main())
