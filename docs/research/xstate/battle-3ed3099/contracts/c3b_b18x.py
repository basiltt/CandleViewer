# -*- coding: utf-8 -*-
"""B18 corrected: a GENUINELY long invoke + a flooded inbox, and the
"denied guard bricks the machine" finding isolated.

The first `priority_probe` in c3_b18.py handed `Stub.svc` a callable that
returned a coroutine; `Stub.mk_s` returns it without awaiting, so the invoke
completed instantly and the inbox was never truly busy. Here the service is
awaited inside the stub, so `cancelling` really is occupied for 400 ms.
"""
import asyncio, json
from xstate_statemachine import Interpreter, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock
from charness import Stub, TraceP, build, SETTLE
from cdrv import cfg_of, mk, step

G_FULL = {"cancel_working_requested": True, "flatten_requested": True,
          "all_accounts_flat": True, "owner_and_elevated": True,
          "owner_and_elevated_and_acknowledged_residual": True}
R = {}


async def busy_priority():
    cfg = cfg_of("B18")
    marks = []

    class SlowSvc:
        def __init__(self, name, secs):
            self.name, self.secs = name, secs

        def __call__(self, interp, ctx, evt):
            marks.append("svc_start:" + self.name)
            return self._run()

        async def _run(self):
            await asyncio.sleep(self.secs)
            marks.append("svc_end:" + self.name)
            return {"ok": True}

    # Stub.mk_s does `v = v(interp, ctx, evt)` then returns v; returning a
    # coroutine from __call__ means the AWAIT happens in the stub's own
    # `async def s`, so we wrap once more.
    async def slow_cx(interp, ctx, evt):
        marks.append("cx_start")
        await asyncio.sleep(0.4)
        marks.append("cx_end")
        return {"ok": True}

    st = Stub(cfg, guard_vals=G_FULL)
    # replace the generated service with a genuinely awaiting one
    logic = st.logic()
    logic.services["cancel_all_working_orders"] = slow_cx
    from xstate_statemachine import create_machine
    m = create_machine(cfg, logic=logic, strict_targets=True)
    clock = SimulatedClock()
    interp = Interpreter(m, clock=clock, max_queue_size=64,
                         overflow_policy=OverflowPolicy.RAISE)
    tp = TraceP()
    interp.use(tp)
    await interp.start()
    await asyncio.sleep(SETTLE)
    await interp.send("ENGAGE", wait=False)
    await asyncio.sleep(0.08)           # now genuinely inside `cancelling`
    busy_ids = sorted(interp.current_state_ids)
    for _ in range(20):
        await interp.send("RETRY_FLATTEN", wait=False)
    qd = getattr(interp, "queue_depth", None)
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    out = {"busy_ids": busy_ids, "queue_depth": qd, "marks_at_flood": list(marks)}
    try:
        rec = await asyncio.wait_for(interp.send_priority("RELEASE"),
                                     timeout=3.0)
        out.update(priority_latency_s=round(loop.time() - t0, 4),
                   changed=rec.changed,
                   error=type(rec.error).__name__ if rec.error else None,
                   ids_after=sorted(interp.current_state_ids),
                   status=interp.status)
    except Exception as e:  # noqa: BLE001
        out.update(priority="%s: %s" % (type(e).__name__, str(e)[:200]),
                   elapsed=round(loop.time() - t0, 3),
                   status=interp.status,
                   ids_after=sorted(interp.current_state_ids))
    await asyncio.sleep(0.9)
    out["final_ids"] = sorted(interp.current_state_ids)
    out["marks"] = marks
    out["unhandled"] = tp.unhandled[:4]
    out["status_end"] = interp.status
    try:
        await interp.stop()
    except Exception:
        pass
    return out


async def denied_release_bricks():
    """A guard-DENIED RELEASE selects no transition; onUnhandled='error'
    flips status to error, and the receipt does not say so."""
    interp, st, tp, clock, m = await mk(
        "B18", {"guard_vals": dict(G_FULL, owner_and_elevated=False)})
    await step(interp, clock, "ENGAGE")
    await asyncio.sleep(0.2)
    before = {"ids": sorted(interp.current_state_ids), "status": interp.status}
    r = await step(interp, clock, "RELEASE")
    after = {"ids": sorted(interp.current_state_ids), "status": interp.status,
             "receipt_changed": r.changed,
             "receipt_error": type(r.error).__name__ if r.error else None,
             "receipt_deferred": getattr(r, "deferred", None),
             "last_error": type(getattr(interp, "last_error", None)).__name__,
             "last_error_str": str(getattr(interp, "last_error", ""))[:180],
             "unhandled": list(tp.unhandled)}
    # is the machine still usable? try a legitimate ENGAGE-era event
    try:
        r2 = await step(interp, clock, "RETRY_FLATTEN")
        after["subsequent_send"] = {"changed": r2.changed,
                                    "status": interp.status}
    except Exception as e:  # noqa: BLE001
        after["subsequent_send"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    try:
        after["snapshot_ok"] = bool(interp.get_persisted_snapshot())
    except Exception as e:  # noqa: BLE001
        after["snapshot_ok"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    try:
        await interp.stop()
    except Exception:
        pass
    return {"before": before, "after": after}


async def main():
    R["busy_priority"] = await busy_priority()
    R["denied_release"] = await denied_release_bricks()


asyncio.run(main())
json.dump(R, open("results/c3b_b18x.json", "w", encoding="utf-8"),
          indent=2, default=str)
print(json.dumps(R, indent=2, default=str))
