# -*- coding: utf-8 -*-
"""P1/P3 re-probe with wait=True (the documented receipt surface).

P1 guardErrorPolicy="raise": the receipt must carry the guard exception.
P3 strict: an undeclared event must be refused AT THE CALL SITE.
P4 onUnhandled="defer": deferred_count / on_unhandled_event visibility with
   a PLAIN `def` service in flight vs an `async def` one.
"""
from __future__ import annotations
import asyncio, json, os, sys
os.environ.setdefault("CV_SVC_STYLE", sys.argv[1] if len(sys.argv) > 1 else "async")
STYLE = os.environ["CV_SVC_STYLE"]
import cv6db as H
from cv6db import Stub


def rdict(r):
    if r is None:
        return {"receipt": None}
    return {a: repr(getattr(r, a))[:220]
            for a in ("ok", "error", "denied", "deferred", "changed",
                      "state_ids", "unhandled")
            if hasattr(r, a)}


async def p1():
    c = H.cfg("B6")
    st = Stub(c, guard_vals={"price_limit_breached": False},
              guard_raise=["price_limit_breached"])
    m, i, p = await H.new_async(c, st)
    d = {}
    try:
        r = await asyncio.wait_for(i.send("SLICE_DUE", wait=True), 5)
        d["call_site_raise"] = False
        d["receipt"] = rdict(r)
    except Exception as e:
        d["call_site_raise"] = True
        d["exc"] = repr(e)
    await H.quiesce(i, 3)
    d.update(states=H.ids(i), guard_errors=p.guard_errors, svc=st.svc_calls)
    surfaced = d.get("call_site_raise") or (
        d.get("receipt", {}).get("error", "None") != "None")
    H.rec("P1w/guard raise carried on wait=True receipt", surfaced,
          json.dumps(d, default=str))
    H.rec("P1w/on_guard_error hook fired", bool(p.guard_errors),
          json.dumps(p.guard_errors))
    # The fallback transition WAS taken (SCXML 5.9 / #152): the crashing
    # guard did not cancel the unguarded candidate.
    H.rec("P1w/unguarded fallback still taken (#152)",
          "submit_child" in st.svc_calls, json.dumps(st.svc_calls))
    await asyncio.wait_for(i.stop(), 5)


async def p3():
    c = H.cfg("B6")
    st = Stub(c)
    m, i, p = await H.new_async(c, st)
    out = {}
    for w in (False, True):
        try:
            r = await asyncio.wait_for(i.send("NOT_A_REAL_EVENT", wait=w), 5)
            out["wait=%s" % w] = {"raised": False, "receipt": rdict(r)}
        except Exception as e:
            out["wait=%s" % w] = {"raised": True, "exc": repr(e)}
    H.rec("P3/strict refuses undeclared event at the call site",
          out["wait=False"]["raised"] and out["wait=True"]["raised"],
          json.dumps(out))
    await asyncio.wait_for(i.stop(), 5)


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


async def p4():
    c = H.cfg("B6")
    gate, release = mkgate()
    st = Stub(c, svc={"submit_child": gate})
    m, i, p = await H.new_async(c, st)
    await asyncio.wait_for(i.send("SLICE_DUE", wait=True), 5)
    await H.quiesce(i, 2)
    mid = H.ids(i)
    r = await asyncio.wait_for(i.send("USER_PAUSE", wait=True), 6)
    during = {"states": H.ids(i), "deferred": i.deferred_count,
              "unhandled": list(p.unhandled), "receipt": rdict(r)}
    release()
    await H.quiesce(i, 8)
    H.rec("P4/deferred across in-flight invoke is OBSERVABLE",
          bool(p.unhandled) and any(d == "deferred" for _e, d in p.unhandled),
          json.dumps({"mid": mid, "during": during, "after": H.ids(i)}))
    H.rec("P4/deferred event replayed after completion",
          H.ids(i) == ["twap.paused"], json.dumps(H.ids(i)))
    await asyncio.wait_for(i.stop(), 5)


async def main():
    for f in (p1, p3, p4):
        try:
            await f()
        except Exception as e:
            import traceback; traceback.print_exc()
            H.rec(f.__name__ + "/CRASH", False, repr(e))
    H.dump("k9_wait.json")

asyncio.run(main())
