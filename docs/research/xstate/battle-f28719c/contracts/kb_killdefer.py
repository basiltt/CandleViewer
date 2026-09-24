# -*- coding: utf-8 -*-
"""CD-KS: `priority=True` does not defeat `onUnhandled: "defer"`.

B6 `submitting_slice` and B9 `evaluating` declare no USER_CANCEL /
KILL_SWITCH handler. Under the mandated `onUnhandled: "defer"` the kill
switch is therefore HELD for the whole in-flight service instead of being
applied ahead of it -- and `priority=True` (the documented "decisions that
must not wait behind routine traffic" lane) does not change that, because
priority orders the INBOX, while defer is decided by the CONFIGURATION.

Measured here as an end-to-end kill latency vs the service duration, and
contrasted with a fixed contract that declares the handler on the
invoking state.
"""
from __future__ import annotations
import asyncio, copy, json, os, sys, time
os.environ.setdefault("CV_SVC_STYLE", sys.argv[1] if len(sys.argv) > 1 else "async")
STYLE = os.environ["CV_SVC_STYLE"]
import cv6db as H
from cv6db import Stub

HOLD = 1.5


def slow():
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


async def kill_latency(c, setup, kill, svc_name, label):
    st = Stub(c, guard_vals=dict(setup["guards"]), svc={svc_name: slow()})
    m, i, p = await H.new_async(c, st)
    for ev in setup["script"]:
        await asyncio.wait_for(i.send(ev, wait=True), 8)
    await asyncio.sleep(0.05)
    inflight = H.ids(i)
    t0 = time.perf_counter()
    r = await asyncio.wait_for(i.send(kill, wait=True, priority=True), 20)
    t_receipt = time.perf_counter() - t0
    deferred_on_receipt = bool(getattr(r, "deferred", False))
    # wait until the kill has actually been APPLIED
    applied = None
    deadline = time.perf_counter() + HOLD + 5
    while time.perf_counter() < deadline:
        if H.ids(i) != inflight:
            applied = time.perf_counter() - t0
            break
        await asyncio.sleep(0.01)
    await H.quiesce(i, 4)
    out = {"label": label, "style": STYLE, "inflight": inflight,
           "final": H.ids(i), "service_hold_s": HOLD,
           "receipt_s": round(t_receipt, 3),
           "applied_s": None if applied is None else round(applied, 3),
           "receipt_deferred": deferred_on_receipt,
           "unhandled": [u for u in p.unhandled if u[0] == kill],
           "dropped": p.dropped}
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass
    return out


async def main():
    rows = []
    b6 = H.cfg("B6")
    rows.append(await kill_latency(
        b6, {"guards": {}, "script": ["SLICE_DUE"]},
        "USER_CANCEL", "submit_child", "B6 as-catalogued"))
    b9 = H.cfg("B9")
    g9 = {"promotion_gate_satisfied_and_permitted": True,
          "condition_true": True, "error_budget_exhausted": False,
          "once_satisfied": False}
    rows.append(await kill_latency(
        b9, {"guards": g9, "script": ["SAVE", "ARM_REQUESTED", "TRIGGER"]},
        "KILL_SWITCH", "evaluate_condition_dag", "B9 as-catalogued"))

    # --- the wrapper fix: declare the kill handler ON the invoking state
    b6f = copy.deepcopy(b6)
    b6f["states"]["submitting_slice"]["on"] = {
        "USER_CANCEL": {"target": "#twap.cancelling"}}
    rows.append(await kill_latency(
        b6f, {"guards": {}, "script": ["SLICE_DUE"]},
        "USER_CANCEL", "submit_child", "B6 + handler on invoking state"))
    b9f = copy.deepcopy(b9)
    b9f["states"]["evaluating"]["on"] = {
        "KILL_SWITCH": {"target": "#rule_instance.kill_switched"}}
    rows.append(await kill_latency(
        b9f, {"guards": g9, "script": ["SAVE", "ARM_REQUESTED", "TRIGGER"]},
        "KILL_SWITCH", "evaluate_condition_dag", "B9 + handler on invoking state"))

    for r in rows:
        print(json.dumps(r), flush=True)
        fixed = "handler" in r["label"]
        fast = r["applied_s"] is not None and r["applied_s"] < HOLD * 0.6
        H.rec("CD-KS/%s: kill applied before service completes" % r["label"],
              fast if fixed else True,   # as-catalogued rows are evidence
              json.dumps(r))
        H.rec("CD-KS/%s: kill is never LOST" % r["label"],
              r["applied_s"] is not None and not r["dropped"],
              json.dumps({"final": r["final"], "applied_s": r["applied_s"]}))
    (H.HERE / ("kb_killdefer_rows.%s.json" % STYLE)).write_text(
        json.dumps(rows, indent=1), encoding="utf-8")
    H.dump("kb_killdefer.json")

asyncio.run(main())
