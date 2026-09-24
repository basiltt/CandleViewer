# -*- coding: utf-8 -*-
"""B18-analogue kill switch into B6/B9, both service styles.

K1  external send_priority while a service is IN FLIGHT: 0 dropped, and
    the latency from issue to application is measured.
K2  N=200 external priority sends beside engine traffic: none charged to
    the chain budget (#180), none dropped.
K3  the `def` lane: how long does a blocking plain service hold the
    macrostep, i.e. what is the kill-switch latency floor?
"""
from __future__ import annotations
import asyncio, json, os, sys, time
os.environ.setdefault("CV_SVC_STYLE", sys.argv[1] if len(sys.argv) > 1 else "async")
STYLE = os.environ["CV_SVC_STYLE"]
import cv6db as H
from cv6db import Stub

HOLD = 1.0


def hold_gate():
    """A service that stays open for HOLD seconds in this pass's style."""
    if STYLE == "async":
        async def held(*_a):
            await asyncio.sleep(HOLD)
            return {"ok": True}
        return lambda *_a: held()
    import time as _t

    def blocking(*_a):
        _t.sleep(HOLD)
        return {"ok": True}
    return blocking


async def k1():
    c = H.cfg("B6")
    st = Stub(c, svc={"submit_child": hold_gate()})
    m, i, p = await H.new_async(c, st)
    await asyncio.wait_for(i.send("SLICE_DUE", wait=True), 5)
    await asyncio.sleep(0.05)
    t0 = time.perf_counter()
    r = await asyncio.wait_for(i.send("USER_CANCEL", wait=True, priority=True), 15)
    lat = time.perf_counter() - t0
    await H.quiesce(i, 6)
    H.rec("K1/priority kill switch applied, nothing dropped",
          H.ids(i) in (["twap.cancelling"], ["twap.cancelled"])
          and not p.dropped,
          json.dumps({"states": H.ids(i), "latency_s": round(lat, 3),
                      "dropped": p.dropped,
                      "receipt_err": repr(getattr(r, "error", None))}))
    H.rec("K1/kill-switch latency <= service duration + slack",
          lat <= HOLD + 1.0,
          "latency=%.3fs  service_hold=%.1fs  style=%s" % (lat, HOLD, STYLE))
    await asyncio.wait_for(i.stop(), 5)
    return lat


async def k2():
    c = H.cfg("B10")
    st = Stub(c, guard_vals={"all_channels_ok": True,
                             "delivery_attempts_left": True})
    m, i, p = await H.new_async(c, st)
    N = 200
    # DISABLE/ENABLE is a declared pair that always has a handler; drive it
    # as priority traffic beside the engine's own delivery completions.
    ok = 0
    errs = []
    for n in range(N):
        ev = "DISABLE" if n % 2 == 0 else "ENABLE"
        try:
            await asyncio.wait_for(i.send(ev, wait=True, priority=True), 5)
            ok += 1
        except Exception as e:
            errs.append(repr(e))
    await H.quiesce(i, 4)
    charged = [d for d in p.dropped if "budget" in str(d[1]).lower()]
    H.rec("K2/200 external priority sends: 0 dropped, 0 charged (#180)",
          ok == N and not p.dropped and not charged,
          json.dumps({"ok": ok, "n": N, "dropped": p.dropped[:5],
                      "errs": errs[:3], "states": H.ids(i)}))
    await asyncio.wait_for(i.stop(), 5)


async def k3():
    """Kill-switch latency floor while a service is in flight."""
    c = H.cfg("B9")
    st = Stub(c, guard_vals={"promotion_gate_satisfied_and_permitted": True,
                             "condition_true": True,
                             "condition_true_and_requires_confirmation": False,
                             "error_budget_exhausted": False,
                             "once_satisfied": False},
              svc={"evaluate_condition_dag": hold_gate()})
    m, i, p = await H.new_async(c, st)
    await asyncio.wait_for(i.send("SAVE", wait=True), 5)
    await asyncio.wait_for(i.send("ARM_REQUESTED", wait=True), 5)
    await asyncio.wait_for(i.send("TRIGGER", wait=True), 5)
    await asyncio.sleep(0.05)
    inflight = H.ids(i)
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(i.send("KILL_SWITCH", wait=True, priority=True), 15)
        to = False
    except asyncio.TimeoutError:
        to = True
    lat = time.perf_counter() - t0
    await H.quiesce(i, 6)
    H.rec("K3/KILL_SWITCH reaches kill_switched during in-flight eval",
          (not to) and H.ids(i) == ["rule_instance.kill_switched"],
          json.dumps({"inflight": inflight, "after": H.ids(i),
                      "latency_s": round(lat, 3), "timeout": to,
                      "unh": p.unhandled[-3:]}))
    H.rec("K3/kill-switch latency floor recorded", True,
          "style=%s latency=%.3fs service_hold=%.1fs" % (STYLE, lat, HOLD))
    await asyncio.wait_for(i.stop(), 5)
    return lat


async def main():
    lats = {}
    for f in (k1, k2, k3):
        try:
            lats[f.__name__] = await f()
        except Exception as e:
            import traceback; traceback.print_exc()
            H.rec(f.__name__ + "/CRASH", False, repr(e))
    print("LATENCIES", STYLE, json.dumps(lats, default=str), flush=True)
    H.dump("ka_killswitch.json")

asyncio.run(main())
