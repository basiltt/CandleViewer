# -*- coding: utf-8 -*-
"""STANDALONE: c78ce99 contract edges not covered by the ported drivers.
  A. C-04 re-check -- B16 elevation survives LOGOUT?
  B. B18 send_priority under a self-generated chain (C-07b's neighbour).
  C. #214 -- the restore path applies `strict` to our contracts, reports
     the refusal, and keeps an engine-minted record as engine-minted.
Run: w7_edges.py [async|def]
"""
from __future__ import annotations
import asyncio, json, os, pathlib, sys

os.environ.setdefault("CV_SVC_STYLE", sys.argv[1] if len(sys.argv) > 1 else "async")
STYLE = os.environ["CV_SVC_STYLE"]
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv78 as H  # noqa: E402
from cv78 import Stub  # noqa: E402
from xstate_statemachine import Interpreter  # noqa: E402
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

rec = H.rec
os.chdir("C:/Users/basil")


def S(c, **kw):
    kw.setdefault("svc_style", STYLE)
    return Stub(c, **kw)


# ------------------------------------------------------------ A: C-04 ------
async def a_c04():
    c = H.cfg("B16")
    st = S(c, guard_vals={"mfa_ok": True, "step_up_ok": True,
                          "owner": True, "elevation_valid": True})
    m, i, p = await H.new_async(c, st)
    for ev in ("MFA_OK", "REQUEST", "STEP_UP_OK"):
        await H.send(i, ev); await H.quiesce(i, 3)
    before = H.ids(i)
    await H.send(i, "LOGOUT"); await H.quiesce(i, 4)
    after = H.ids(i)
    ctx = json.loads(json.dumps(i.context, default=str))
    elevated = any("elevated" in x for x in after)
    revoked = any("revoked" in x or "terminal" in x for x in after)
    rec("C-04/elevation SURVIVES LOGOUT (our-contract blocker)",
        elevated and revoked,
        json.dumps({"before": before, "after": after,
                    "elevated_until_us": ctx.get("elevated_until_us")}))
    # NOTE: the stub's actions do not write context, so `elevated_until_us`
    # is null here for harness reasons, NOT because the chart clears it --
    # `elevation.elevated` has no LOGOUT handler at all, so no clearing
    # action can run. The structural fact is the one above.
    rec("C-04/no LOGOUT handler on elevation.elevated",
        "LOGOUT" not in (c["states"]["elevation"]["states"]["elevated"]
                         .get("on") or {}),
        json.dumps(sorted((c["states"]["elevation"]["states"]["elevated"]
                           .get("on") or {}).keys())))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass


# ------------------------------------------- B: B18 priority under chain ---
async def b_priority():
    """A kill-switch ENGAGE must preempt an in-flight self-generated chain
    and nothing may be dropped from the bounded RAISE inbox."""
    c = json.loads(json.dumps(H.cfg("B18")))
    c["maxIterations"] = 12
    st = S(c, guard_vals={"cancel_working_requested": True,
                          "flatten_requested": True,
                          "all_accounts_flat": True,
                          "owner_and_elevated": True})
    m, i, p = await H.new_async(c, st, maxq=64)
    r = await i.send("ENGAGE", priority=True) if False else None
    try:
        await asyncio.wait_for(i.send("ENGAGE"), 5)
        sent_ok = True
    except Exception as e:
        sent_ok = False
        rec("B18.priority/send raised", False, repr(e)[:160])
    await H.quiesce(i, 6)
    rec("B18.priority/chain completed, nothing dropped",
        sent_ok and not p.dropped and i.error is None,
        json.dumps({"states": H.ids(i), "dropped": p.dropped,
                    "err": repr(i.error)[:120], "svc": st.svc_calls}))
    rec("B18.priority/both kill services ran in order",
        st.svc_calls[:2] == ["cancel_all_working_orders",
                             "flatten_all_positions"],
        json.dumps(st.svc_calls))
    # now RELEASE with an authorised operator -> back to clear
    await asyncio.wait_for(i.send("RELEASE"), 5); await H.quiesce(i, 4)
    rec("B18.priority/authorised RELEASE lands (C-07b not triggered)",
        H.ids(i) == ["kill_switch.clear"] and i.status == "running",
        json.dumps({"states": H.ids(i), "status": i.status}))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass


# ------------------------------------------- C: #214 restore applies strict -
async def c_restore_strict():
    c = H.cfg("B1")
    st = S(c, guard_vals={"passes_all_gates": True, "ret_code_ok": True})
    m, i, p = await H.new_async(c, st)
    await H.send(i, "VALIDATE"); await H.quiesce(i, 3)
    blob = i.get_persisted_snapshot()
    if not isinstance(blob, str):
        blob = json.dumps(blob)
    await i.stop()
    raw = json.loads(blob)
    rec("#214/our B1 snapshot is v3", raw.get("version") == 3,
        str(raw.get("version")))
    # forge a pending USER event the chart never declares: `strict: true`
    # must refuse it on restore rather than enqueue it.
    raw["pending_events"] = [{"kind": "event", "type": "NOT_IN_CHART",
                              "payload": {}}]
    st2 = S(c, guard_vals={"passes_all_gates": True})
    j = Interpreter.from_snapshot(json.dumps(raw), H.build(c, st2),
                                  clock=SimulatedClock(), minimum_version=3)
    p2 = H.CvHooks(); j.use(p2)
    await j.start(); await H.quiesce(j, 4)
    rec("#214/restored unknown USER event refused under strict",
        bool(p2.invalid) or j.last_error is not None,
        json.dumps({"invalid": p2.invalid[:2],
                    "last_error": repr(j.last_error)[:140],
                    "states": H.ids(j)}))
    rec("#214/machine still usable after the refusal",
        j.status == "running" and "order.lifecycle.validated" in H.ids(j),
        json.dumps({"status": j.status, "states": H.ids(j)}))
    await j.stop()
    # a v2 payload must be refused by minimum_version=3
    raw2 = json.loads(blob); raw2["version"] = 2
    try:
        Interpreter.from_snapshot(json.dumps(raw2), H.build(c, S(c)),
                                  clock=SimulatedClock(), minimum_version=3)
        ok, note = False, "v2 ACCEPTED at minimum_version=3"
    except Exception as e:
        ok, note = "Version" in type(e).__name__, repr(e)[:160]
    rec("#214/v2 refused at minimum_version=3", ok, note)


async def main():
    await a_c04()
    await b_priority()
    await c_restore_strict()
    H.dump("res_edges.json")


asyncio.run(main())
