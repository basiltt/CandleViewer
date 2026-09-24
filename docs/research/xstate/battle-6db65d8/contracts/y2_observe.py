# -*- coding: utf-8 -*-
"""Is the rollback+onDone spin bounded, and is the trip OBSERVABLE?

Records: final service-call count, the receipt the caller got, interp.error,
plugin on_error/on_transition_failed/on_action_error, and whether the
machine is left parked in the invoking state.
"""
from __future__ import annotations
import asyncio, json, logging, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)

BASE = {
    "id": "m", "initial": "idle",
    "actionErrorPolicy": "rollback", "guardErrorPolicy": "raise",
    "strictTargets": True, "strict": True, "context": {},
    "states": {
        "idle": {"on": {"GO": {"target": "#m.arm"}}},
        "arm": {"invoke": {"id": "s", "src": "svc",
                           "onDone": {"target": "#m.done", "actions": ["boom"]},
                           "onError": {"target": "#m.err"}}},
        "done": {"type": "final"}, "err": {"type": "final"},
    },
}


class P(PluginBase):
    def __init__(self):
        self.errors, self.tf, self.ae = [], [], []

    def on_error(self, i, e):
        self.errors.append(repr(e))

    def on_transition_failed(self, i, *a):
        self.tf.append(repr(a[-1]))

    def on_action_error(self, i, a, e):
        self.ae.append(repr(e))


async def run(style, maxi, settle=4.0):
    calls = []
    cfg = json.loads(json.dumps(BASE))
    if maxi is not None:
        cfg["maxIterations"] = maxi

    def boom(i, c, e, a):
        raise RuntimeError("boom")

    async def asvc(i, c, e):
        calls.append(1); return {"ok": True}

    def dsvc(i, c, e):
        calls.append(1); return {"ok": True}

    m = create_machine(cfg, logic=MachineLogic(
        actions={"boom": boom},
        services={"svc": asvc if style == "async" else dsvc}, strict=True))
    i = Interpreter(m, clock=SimulatedClock())
    p = P(); i.use(p)
    await i.start()
    t0 = time.perf_counter()
    try:
        r = await asyncio.wait_for(i.send("GO"), 30)
        receipt = {"ok": getattr(r, "ok", None),
                   "error": repr(getattr(r, "error", None))}
    except asyncio.TimeoutError:
        receipt = "SEND-TIMEOUT"
    send_sec = round(time.perf_counter() - t0, 2)
    n_at_send = len(calls)
    # let it run on: a bounded chain must stop growing.
    await asyncio.sleep(settle)
    n1 = len(calls)
    await asyncio.sleep(settle)
    n2 = len(calls)
    out = {"style": style, "maxIterations": maxi, "limit_effective": maxi or 1000,
           "send_sec": send_sec, "receipt": receipt,
           "svc_at_send": n_at_send, "svc_after": n1, "svc_after2": n2,
           "bounded": n2 == n1,
           "final_svc_calls": n2,
           "states": sorted(i.current_state_ids), "status": i.status,
           "interp_error": repr(i.error),
           "last_error": repr(i.last_error),
           "plugin_on_error": p.errors[:2], "n_on_error": len(p.errors),
           "n_transition_failed": len(p.tf), "n_action_error": len(p.ae)}
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception as e:
        out["stop"] = repr(e)
    return out


async def main():
    res = []
    for maxi in (20, 100, None):
        for style in ("async", "def"):
            r = await run(style, maxi)
            res.append(r); print(json.dumps(r), flush=True)
    json.dump(res, open("y2_observe.json", "w"), indent=1)


asyncio.run(main())
