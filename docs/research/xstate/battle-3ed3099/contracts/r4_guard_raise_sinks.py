# -*- coding: utf-8 -*-
"""R4 -- where does a `guardErrorPolicy: "raise"` failure GO?

R3 established the failure is reported on `Receipt.error` for a
`send(..., wait=True)`. Two order-path-relevant holes remain:

  (a) fire-and-forget: `send()` without `wait=True` -- is the crash
      observable anywhere (interpreter.error, status, plugin hook)?
  (b) engine-event path: the guard on an `invoke` `onDone` branch has NO
      caller and therefore NO receipt. R3 control 3 left B8 sitting in
      `verifying` with status=running and error=None. Is that a permanent
      strand, and is it observable?

(b) is the safety-critical one: B8 is `actionErrorPolicy: "fail"` precisely
so a half-applied safety step halts.
"""
from __future__ import annotations

import asyncio
import json

import cvlib
from cvlib import Rig


class HookP(cvlib.TraceP):
    def __init__(self):
        super().__init__()
        self.resolve_errors = []
        self.plugin_errors = []

    def on_resolve_error(self, *a, **k):  # noqa: ANN001
        self.resolve_errors.append((a[1:], k))

    def on_plugin_error(self, *a, **k):  # noqa: ANN001
        self.plugin_errors.append((a[1:], k))


async def case_a():
    cfg = cvlib.load("B8")
    rig = Rig(guard_values={"exchange_reports_sl": True},
              guard_raises={"tightens_only"})
    m = cvlib.build(cfg, rig)
    from xstate_statemachine import Interpreter
    from xstate_statemachine.clock import SimulatedClock

    interp = Interpreter(m, clock=SimulatedClock())
    plug = HookP()
    interp.use(plug)
    await interp.start()
    await interp.send("POSITION_OPENED")
    await asyncio.sleep(cvlib.SETTLE * 3)
    await interp.send("TIGHTEN_SL")  # fire and forget -- NO receipt
    await asyncio.sleep(cvlib.SETTLE * 3)
    out = {
        "case": "(a) fire-and-forget send, guard raises",
        "states": sorted(interp.current_state_ids),
        "status": interp.status,
        "interpreter.error": repr(interp.error),
        "last_error": repr(getattr(interp, "last_error", "<absent>")),
        "last_transition_ok": getattr(interp, "last_transition_ok", "<absent>"),
        "plugin.dropped": plug.dropped,
        "plugin.unhandled": plug.unhandled,
        "plugin.on_resolve_error": plug.resolve_errors,
        "observable_anywhere": False,
    }
    out["observable_anywhere"] = bool(
        interp.error or plug.dropped or plug.resolve_errors
        or interp.status != "running"
    )
    await interp.stop()
    return out


async def case_b():
    cfg = cvlib.load("B8")
    rig = Rig(guard_raises={"exchange_reports_sl"})
    m = cvlib.build(cfg, rig)
    from xstate_statemachine import Interpreter
    from xstate_statemachine.clock import SimulatedClock

    interp = Interpreter(m, clock=SimulatedClock())
    plug = HookP()
    interp.use(plug)
    await interp.start()
    await interp.send("POSITION_OPENED")
    await asyncio.sleep(cvlib.SETTLE * 5)
    stuck = sorted(interp.current_state_ids)
    # keep poking: is this permanent?
    pokes = []
    for ev in ("SCAN_DUE", "SL_DEADLINE", "TIGHTEN_SL", "POSITION_OPENED"):
        try:
            r = await interp.send(ev, wait=True)
            pokes.append((ev, getattr(r, "changed", None),
                          repr(getattr(r, "error", None)),
                          getattr(r, "deferred", None)))
        except Exception as exc:  # noqa: BLE001
            pokes.append((ev, "RAISED", type(exc).__name__, None))
        await asyncio.sleep(cvlib.SETTLE)
    out = {
        "case": "(b) guard on invoke onDone raises -- no caller, no receipt",
        "stuck_at": stuck,
        "after_pokes": sorted(interp.current_state_ids),
        "pokes": pokes,
        "status": interp.status,
        "interpreter.error": repr(interp.error),
        "deferred_count": interp.deferred_count,
        "pending_invocations": [repr(p) for p in interp.pending_invocations()],
        "plugin.dropped": plug.dropped,
        "plugin.unhandled": plug.unhandled,
        "plugin.on_resolve_error": plug.resolve_errors,
        "sl_region_is_unprotected_and_silent": (
            "position_protection.sl.verifying" in stuck
            and interp.error is None
            and interp.status == "running"
        ),
    }
    await interp.stop()
    return out


async def main():
    rows = [await case_a(), await case_b()]
    print(json.dumps(rows, indent=2, default=str))


asyncio.run(main())
