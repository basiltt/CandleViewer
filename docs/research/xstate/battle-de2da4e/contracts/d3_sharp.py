# -*- coding: utf-8 -*-
"""n3: sharp edges on 19cb1f1 for B16-B20.
  A. C-07b: is the B18 kill switch bricked by a guard-denied RELEASE?
  B. #207 stranded hook on the mandated rollback+onDone drive, both lanes.
  C. #204: invoke must NOT arm when its state is left in the same macrostep.
  D. sync parity: configuration + action trace + service-call trace.
Run: n3_sharp.py [async|def]
"""
from __future__ import annotations
import asyncio, json, os, sys
os.environ["CV_SVC_STYLE"] = sys.argv[1] if len(sys.argv) > 1 else "async"
STYLE = os.environ["CV_SVC_STYLE"]
import cvde as H
from cvde import Stub
rec = H.rec

def S(c, **kw):
    kw.setdefault("svc_style", STYLE); return Stub(c, **kw)

def budgeted(c, n):
    c2 = json.loads(json.dumps(c)); c2["maxIterations"] = n; return c2

GV18 = {"cancel_working_requested": True, "flatten_requested": True,
        "all_accounts_flat": True, "owner_and_elevated": False,
        "owner_and_elevated_and_acknowledged_residual": True}

# ---------------------------------------------------------------- A: C-07b --
async def a_c07b():
    c = H.cfg("B18")
    st = S(c, guard_vals=dict(GV18))
    m, i, p = await H.new_async(c, st)
    r1 = await H.send(i, "ENGAGE"); await H.quiesce(i, 4)
    r2 = await H.send(i, "RELEASE"); await H.quiesce(i, 4)
    st_after = H.ids(i); status = i.status; err = repr(i.error)
    # now the operator IS authorised - does a legitimate RELEASE still work?
    st.guard_vals["owner_and_elevated"] = True
    r3 = await H.send(i, "RELEASE"); await H.quiesce(i, 4)
    final = H.ids(i)
    rec("C-07b/denied RELEASE is fatal",
        status == "error" or "UnhandledEventError" in err,
        json.dumps({"after_denied": st_after, "status": status, "err": err[:140]}))
    rec("C-07b/kill switch BRICKED (valid RELEASE cannot land)",
        final != ["kill_switch.clear"],
        json.dumps({"final": final, "r3": {k: v for k, v in r3.items() if k != 'receipt'},
                    "status": i.status}))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass

# ------------------------------------------------------ B: #207 stranded ----
async def b_stranded(bid, svc_state, raiser, gv, ev, limit):
    c = budgeted(H.cfg(bid), limit)
    st = S(c, guard_vals=dict(gv), raising=[raiser])
    m, i, p = await H.new_async(c, st)
    await H.send(i, ev, timeout=5)
    prev, laps = -1, []
    for _ in range(30):
        await H.quiesce(i, 4)
        n = len(st.svc_calls)
        laps.append(n)
        if n == prev:
            break
        prev = n
    le = repr(i.last_error)
    stranded = list(p.stranded)
    dormant = getattr(i, "has_dormant_invocations", None)
    pend = getattr(i, "pending_invocations", None)
    try:
        pend = pend() if callable(pend) else pend
    except Exception as e:
        pend = repr(e)
    ids = H.ids(i)
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass
    return {"plateau": prev, "limit": limit, "state": ids, "stranded": stranded,
            "dormant": bool(dormant), "pending": [str(x) for x in (pend or [])],
            "last_error": le[:110], "laps": laps}

async def b_all():
    r18 = await b_stranded("B18", "flattening", "page_owner",
                           dict(GV18, all_accounts_flat=False), "ENGAGE", 5)
    rec("#207/B18 rollback+onDone strands observably",
        r18["stranded"] and "RunawayChainError" in r18["last_error"]
        and r18["dormant"], json.dumps(r18))
    rec("#207/B18 plateau == maxIterations+2 svc calls",
        r18["plateau"] == r18["limit"] + 2, json.dumps(
            {"plateau": r18["plateau"], "limit": r18["limit"]}))
    r19 = await b_stranded("B19", "diffing", "store_divergences",
                           {"divergences_found_and_auto_remediate": True,
                            "unresolved_divergences": False,
                            "failures_exhausted": False}, "SWEEP_DUE", 25)
    rec("#207/B19 rollback+onDone strands observably",
        r19["stranded"] and "RunawayChainError" in r19["last_error"]
        and r19["dormant"], json.dumps(r19))
    rec("#207/B19 plateau == maxIterations+2 svc calls",
        r19["plateau"] == r19["limit"] + 2, json.dumps(
            {"plateau": r19["plateau"], "limit": r19["limit"]}))

# --------------------------------------------- C: #204 invoke not armed -----
async def c_no_arm():
    """B18 'cancelling' carries invoke cx.  Give it an `always` that leaves
    cancelling in the same macrostep it is entered: the service must never
    be called, on either engine and either spelling."""
    c = H.cfg("B18")
    c["states"]["cancelling"]["always"] = [{"target": "#kill_switch.engaged"}]
    st = S(c, guard_vals=dict(GV18, owner_and_elevated=True))
    o = await H.drive(c, st, ["ENGAGE"])
    rec("#204/invoke never arms for a state exited in the same macrostep",
        st.svc_calls == [] and "kill_switch.engaged" in o["states"][0],
        json.dumps({"st": o["states"], "svc": st.svc_calls}))
    so = H.drive_sync(c, Stub(c, guard_vals=dict(GV18, owner_and_elevated=True), svc_style="def"),
                      ["ENGAGE"])
    rec("#204/sync engine same",
        so["svc_calls"] == [] and so["states"] == ["kill_switch.engaged"],
        json.dumps({"st": so["states"], "svc": so["svc_calls"]}))

# -------------------------------------------------- D: sync parity traces ---
CASES = [
    ("B16", {}, ["MFA_OK", "REQUEST", "STEP_UP_OK", "REQUEST"]),
    ("B17", {"all_evidence_present": True,
             "owner_and_elevated_and_evidence_still_valid": True,
             "owner_and_elevated": True},
     ["EVIDENCE_RECORDED", "ENABLE_REQUESTED", "DISABLE_REQUESTED"]),
    ("B18", {"cancel_working_requested": True, "flatten_requested": True,
             "all_accounts_flat": True, "owner_and_elevated": True},
     ["ENGAGE", "RELEASE"]),
    ("B19", {"divergences_found_and_auto_remediate": True,
             "unresolved_divergences": False, "failures_exhausted": False},
     ["SWEEP_DUE"]),
    ("B20", {"breaches_daily_loss_cap": True, "until_mode_is_time_based": True},
     ["PNL_UPDATE", "EXPIRY_DUE"]),
]

async def d_parity():
    for bid, gv, script in CASES:
        c = H.cfg(bid)
        sa = S(c, guard_vals=dict(gv))
        oa = await H.drive(c, sa, script, snapshots=False)
        ss = Stub(c, guard_vals=dict(gv), svc_style="def")  # sync engine refuses async svcs (NotSupportedError)
        os_ = H.drive_sync(c, ss, script)
        same = (oa["states"] == os_["states"]
                and oa["actions"] == os_["actions"]
                and sa.svc_calls == ss.svc_calls)
        rec("parity/%s config+action+service trace" % bid, same,
            json.dumps({"async": {"st": oa["states"], "n_act": len(oa["actions"]),
                                  "svc": sa.svc_calls},
                        "sync": {"st": os_["states"], "n_act": len(os_["actions"]),
                                 "svc": ss.svc_calls},
                        "act_delta": [x for x in oa["actions"]
                                      if x not in os_["actions"]]}))

async def main():
    await a_c07b(); await b_all(); await c_no_arm(); await d_parity()
    H.dump("results/p3_sharp.json")

asyncio.run(main())
