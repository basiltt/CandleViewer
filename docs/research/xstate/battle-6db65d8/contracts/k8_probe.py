# -*- coding: utf-8 -*-
"""Probe the two candidate findings from k7 on 6db65d8, both styles.

P1  guardErrorPolicy: "raise" -- does a crashing guard surface on the
    caller's receipt, or is it silently a denial?
P2  onUnhandled: "defer" across an in-flight invoke -- is the event HELD
    until the completion lands, or applied immediately (interrupting the
    invoke)?  We record the exact action/transition ordering.
"""
from __future__ import annotations
import asyncio, json, os, sys

os.environ.setdefault("CV_SVC_STYLE", sys.argv[1] if len(sys.argv) > 1 else "async")
STYLE = os.environ["CV_SVC_STYLE"]

import cv6db as H
from cv6db import Stub


def mkgate():
    if STYLE == "async":
        ev = asyncio.Event()

        async def held():
            await ev.wait()
            return {"ok": True}
        return (lambda *_a: held()), (lambda: ev.set())
    import threading
    tev = threading.Event()

    def blocking(*_a):
        tev.wait(20)
        return {"ok": True}
    return blocking, (lambda: tev.set())


async def p1_guard_raise():
    c = H.cfg("B6")
    st = Stub(c, guard_vals={"price_limit_breached": False},
              guard_raise=["price_limit_breached"])
    m, i, p = await H.new_async(c, st)
    detail = {}
    try:
        r = await asyncio.wait_for(i.send("SLICE_DUE"), 5)
        detail["raised_at_call_site"] = False
        detail["receipt_repr"] = repr(r)[:300]
        for a in ("ok", "error", "status", "deferred", "transitioned"):
            if hasattr(r, a):
                detail["receipt." + a] = repr(getattr(r, a))[:200]
    except Exception as e:
        detail["raised_at_call_site"] = True
        detail["exc"] = repr(e)
    await H.quiesce(i, 3)
    detail.update(states=H.ids(i), guard_errors=p.guard_errors,
                  errors=p.errors, transition_failed=p.transition_failed,
                  last_error=repr(getattr(i, "last_error", None)),
                  i_error=repr(i.error), status=i.status,
                  guard_calls=st.guard_calls)
    # Did the machine take the *fallback* transition (silent denial) or
    # refuse the event entirely?
    H.rec("P1/guard-raise surfaces to caller or hook",
          detail.get("raised_at_call_site")
          or bool(p.guard_errors) or detail["receipt.error"] not in ("None",),
          json.dumps(detail, default=str))
    H.rec("P1/guard-raise is NOT a silent denial",
          H.ids(i) != ["twap.submitting_slice"],
          json.dumps({"states": H.ids(i), "svc": st.svc_calls}))
    await asyncio.wait_for(i.stop(), 5)


async def p2_defer_hold():
    c = H.cfg("B6")
    gate, release = mkgate()
    st = Stub(c, guard_vals={"price_limit_breached": False,
                             "slice_qty_below_min_roll_forward": False},
              svc={"submit_child": gate})
    m, i, p = await H.new_async(c, st)
    await asyncio.wait_for(i.send("SLICE_DUE"), 5)
    await H.quiesce(i, 2)
    mid = {"states": H.ids(i), "svc": list(st.svc_calls)}
    r = await asyncio.wait_for(i.send("USER_PAUSE"), 5)
    await H.quiesce(i, 2)
    during = {"states": H.ids(i), "deferred": i.deferred_count,
              "unhandled": list(p.unhandled),
              "transitions": list(p.transitions)}
    release()
    await H.quiesce(i, 8)
    after = {"states": H.ids(i), "deferred": i.deferred_count,
             "transitions": list(p.transitions), "actions": list(p.actions)}
    # The contract obligation: while the invoke is in flight the machine is
    # still in `submitting_slice`; USER_PAUSE lands only after done.invoke.
    held_during = during["states"] == ["twap.submitting_slice"]
    applied_after = after["states"] == ["twap.paused"]
    H.rec("P2/USER_PAUSE HELD while invoke in flight", held_during,
          json.dumps({"mid": mid, "during": during}))
    H.rec("P2/USER_PAUSE applied after completion", applied_after,
          json.dumps(after))
    H.rec("P2/deferred_count visible while held",
          during["deferred"] == 1,
          json.dumps({"deferred_during": during["deferred"],
                      "deferred_after": after["deferred"],
                      "unhandled": during["unhandled"]}))
    await asyncio.wait_for(i.stop(), 5)


async def main():
    await p1_guard_raise()
    await p2_defer_hold()
    H.dump("k8_probe.json")


asyncio.run(main())
