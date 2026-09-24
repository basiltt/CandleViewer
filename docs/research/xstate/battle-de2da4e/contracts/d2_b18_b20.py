# -*- coding: utf-8 -*-
"""m4: B18 KillSwitch, B19 Reconciliation, B20 RiskLockout -- happy path,
every catalogue invariant, the OC fixes, and the three mandated explicit
drives:
  (1) rollback + invoke.onDone
  (2) always -> invoked child
  (3) B18 send_priority under a self-generated chain (0 dropped, kill preempts)
Snapshot/restore at every quiescence via cv19.drive.
Run twice: `n2_b18_b20.py async` then `m4_b18_b20.py def`.
"""
from __future__ import annotations
import asyncio, json, os, sys

os.environ["CV_SVC_STYLE"] = sys.argv[1] if len(sys.argv) > 1 else "async"
STYLE = os.environ["CV_SVC_STYLE"]

import cvde as H
from cvde import Stub


def S(c, **kw):
    kw.setdefault("svc_style", STYLE)
    return Stub(c, **kw)


def leaves(o):
    return [s.split(".", 1)[1] for s in o["states"]]


def budgeted(c, n):
    """maxIterations is a MACHINE-level field on this build, not an
    Interpreter kwarg -- so the budget goes into the config."""
    c2 = json.loads(json.dumps(c))
    c2["maxIterations"] = n
    return c2


rec = H.rec


# ===================================================================== B18 ==
async def b18():
    c = H.cfg("B18")
    GV = {"cancel_working_requested": True, "flatten_requested": True,
          "all_accounts_flat": True, "owner_and_elevated": True,
          "owner_and_elevated_and_acknowledged_residual": True}

    # happy: ENGAGE -> engaging -always-> cancelling -> flattening -> engaged
    st = S(c, guard_vals=dict(GV))
    o = await H.drive(c, st, ["ENGAGE", "RELEASE"])
    rec("B18/happy engage+release",
        leaves(o) == ["clear"] and o["snapshot_ok"]
        and st.svc_calls == ["cancel_all_working_orders",
                             "flatten_all_positions"],
        json.dumps({"st": o["states"], "svc": st.svc_calls,
                    "snap": o["snapshot_ok"], "notes": o["notes"]}))

    # (2) always -> invoked child: engaging.always fires cancelling's invoke
    st2 = S(c, guard_vals=dict(GV))
    o2 = await H.drive(c, st2, ["ENGAGE"])
    ai = o2["actions"].index("broadcast_kill_switch")
    rec("B18/always -> invoked child",
        "cancel_all_working_orders" in st2.svc_calls
        and "kill_switch.engaging" not in o2["states"],
        json.dumps({"st": o2["states"], "svc": st2.svc_calls,
                    "tr": o2["transitions"]}))
    # always NOT taken when the guard is false -> straight to engaged, no invoke
    st3 = S(c, guard_vals=dict(GV, cancel_working_requested=False))
    o3 = await H.drive(c, st3, ["ENGAGE"])
    rec("B18/always guard false -> engaged, no service",
        leaves(o3) == ["engaged"] and st3.svc_calls == [],
        json.dumps({"st": o3["states"], "svc": st3.svc_calls}))

    # INV-B18-b: blocking precedes every outward effect
    acts = o2["actions"]
    rec("B18/INV-b block precedes outward effects",
        acts.index("block_new_orders_immediately")
        < acts.index("broadcast_kill_switch"),
        json.dumps(acts[:6]))

    # INV-B18-c: incomplete flatten is a visible critical state that pages
    st4 = S(c, guard_vals=dict(GV, all_accounts_flat=False))
    o4 = await H.drive(c, st4, ["ENGAGE"])
    rec("B18/INV-c incomplete flatten pages + is visible",
        leaves(o4) == ["engaged_incomplete"] and "page_owner" in o4["actions"],
        json.dumps({"st": o4["states"], "acts": o4["actions"][-3:]}))

    # INV-B18-c2: RETRY_FLATTEN re-invokes and can complete
    st5 = S(c, guard_vals=dict(GV, all_accounts_flat=False))
    o5 = await H.drive(c, st5, ["ENGAGE", "RETRY_FLATTEN"])
    rec("B18/INV-c2 RETRY_FLATTEN re-invokes",
        st5.svc_calls.count("flatten_all_positions") == 2,
        json.dumps({"st": o5["states"], "svc": st5.svc_calls}))

    # INV-B18-d: release requires owner + elevation  (C-07b territory)
    st6 = S(c, guard_vals=dict(GV, owner_and_elevated=False))
    o6 = await H.drive(c, st6, ["ENGAGE", "RELEASE", "RELEASE"])
    rec("B18/INV-d release denied stays blocked",
        "clear" not in leaves(o6),
        json.dumps({"st": o6["states"], "unh": o6["unhandled"],
                    "err": o6["error"], "notes": o6["notes"]}))

    # INV-B18-e: service error -> engaged_incomplete + critical alert
    st7 = S(c, guard_vals=dict(GV),
            svc={"flatten_all_positions": RuntimeError("venue down")})
    o7 = await H.drive(c, st7, ["ENGAGE"])
    rec("B18/INV-e onError -> incomplete + alert",
        leaves(o7) == ["engaged_incomplete"]
        and "raise_critical_alert" in o7["actions"],
        json.dumps({"st": o7["states"], "acts": o7["actions"][-4:],
                    "svc_err": o7["service_errors"][:1]}))

    # (1) rollback + invoke.onDone, EXPLICITLY driven, bounded
    cb = budgeted(c, 5)
    st8 = S(cb, guard_vals=dict(GV, all_accounts_flat=False),
            raising=["page_owner"])
    m, i, p = await H.new_async(cb, st8)
    r = await H.send(i, "ENGAGE", timeout=5)
    await H.quiesce(i, 15)
    n1 = len(st8.svc_calls)
    await H.quiesce(i, 15)
    n2 = len(st8.svc_calls)
    le = repr(i.last_error)
    ids8 = H.ids(i)
    await i.stop()
    rec("B18/rollback+onDone bounded (CV-221-01)",
        n1 == n2 and n1 <= 7 and "RunawayChainError" in le,
        json.dumps({"svc_t1": n1, "svc_t2": n2, "st": ids8,
                    "last_error": le[:120]}))


# ===================================================== (3) priority lane ====
async def b18_priority():
    """B18 send_priority under a SELF-GENERATED chain: no priority send is
    shed as chain_budget, and the kill press pre-empts the chain."""
    c = H.cfg("B18")
    GV = {"cancel_working_requested": True, "flatten_requested": True,
          "all_accounts_flat": False}
    # A runaway self-generated chain is open (raising page_owner, budget 50).
    cb = budgeted(c, 50)
    st = S(cb, guard_vals=dict(GV), raising=["page_owner"])
    m, i, p = await H.new_async(cb, st)
    # start the chain, do NOT wait for it
    task = asyncio.ensure_future(i.send("ENGAGE", wait=False))
    sent, errs = 0, []
    for n in range(12):
        try:
            await i.send_priority("RELEASE", wait=False)
            sent += 1
        except Exception as e:
            errs.append(repr(e))
        await asyncio.sleep(0.002)
    await H.quiesce(i, 12)
    try:
        await asyncio.wait_for(task, 3)
    except Exception as e:
        errs.append("engage:%r" % (e,))
    shed = [(t, r) for t, r in p.dropped if "budget" in str(r).lower()]
    rec("B18/priority sends never shed as chain_budget",
        not shed, json.dumps({"sent": sent, "dropped": p.dropped[:6],
                              "shed": shed, "errs": errs[:3]}))
    rec("B18/priority lane accepted every kill press",
        sent == 12, json.dumps({"sent": sent, "errs": errs[:3]}))
    await i.stop()


# ===================================================================== B19 ==
async def b19():
    c = H.cfg("B19")
    GV = {"divergences_found_and_auto_remediate": False,
          "unresolved_divergences": False, "failures_exhausted": False}
    st = S(c, guard_vals=dict(GV))
    o = await H.drive(c, st, ["SWEEP_DUE"])
    rec("B19/happy sweep -> idle",
        leaves(o) == ["idle"] and o["snapshot_ok"]
        and st.svc_calls == ["fetch_exchange_state", "diff_against_local"],
        json.dumps({"st": o["states"], "svc": st.svc_calls,
                    "snap": o["snapshot_ok"], "notes": o["notes"]}))

    # INV-B19-a: divergences -> remediate -> report
    st2 = S(c, guard_vals=dict(GV, divergences_found_and_auto_remediate=True))
    o2 = await H.drive(c, st2, ["SWEEP_DUE"])
    rec("B19/INV-a auto-remediation path",
        "apply_remediations" in st2.svc_calls
        and "store_remediations" in o2["actions"] and leaves(o2) == ["idle"],
        json.dumps({"st": o2["states"], "svc": st2.svc_calls}))

    # (2) always -> divergent (the always side)
    st3 = S(c, guard_vals=dict(GV, unresolved_divergences=True))
    o3 = await H.drive(c, st3, ["SWEEP_DUE"])
    rec("B19/always -> divergent + alert",
        leaves(o3) == ["divergent"]
        and "raise_divergence_alert" in o3["actions"],
        json.dumps({"st": o3["states"], "tr": o3["transitions"][-2:]}))

    # retry ladder: onError -> backing_off -> RETRY_DUE -> fetching
    st4 = S(c, guard_vals=dict(GV),
            svc={"fetch_exchange_state": RuntimeError("net")})
    o4 = await H.drive(c, st4, ["SWEEP_DUE", "RETRY_DUE"])
    rec("B19/onError -> backing_off -> retry",
        st4.svc_calls.count("fetch_exchange_state") == 2
        and "bump_failures" in o4["actions"],
        json.dumps({"st": o4["states"], "svc": st4.svc_calls}))

    # failures exhausted -> stale_lockout (critical, locks account)
    st5 = S(c, guard_vals=dict(GV, failures_exhausted=True),
            svc={"fetch_exchange_state": RuntimeError("net")})
    o5 = await H.drive(c, st5, ["SWEEP_DUE"])
    rec("B19/INV-b failures exhausted -> stale_lockout",
        leaves(o5) == ["stale_lockout"]
        and "lock_account_for_new_orders" in o5["actions"],
        json.dumps({"st": o5["states"], "acts": o5["actions"][-3:]}))

    # C-06: operator cannot clear stale_lockout
    st6 = S(c, guard_vals=dict(GV, failures_exhausted=True),
            svc={"fetch_exchange_state": RuntimeError("net")})
    o6 = await H.drive(c, st6, ["SWEEP_DUE", "OPERATOR_RESOLVED"])
    rec("B19/INV-b2 operator can clear stale_lockout",
        leaves(o6) != ["stale_lockout"],
        json.dumps({"st": o6["states"], "unh": o6["unhandled"],
                    "def": o6["deferred"]}))

    # CANCEL during an in-flight fetch (deferral / C-02)
    st7 = S(c, guard_vals=dict(GV))
    o7 = await H.drive(c, st7, ["SWEEP_DUE", "CANCEL"])
    rec("B19/CANCEL lands", leaves(o7) in (["idle"],),
        json.dumps({"st": o7["states"], "unh": o7["unhandled"]}))

    # (1) rollback + invoke.onDone on B19, bounded
    cb = budgeted(c, 25)
    st8 = S(cb, guard_vals=dict(GV, divergences_found_and_auto_remediate=True),
            raising=["store_divergences"])
    m, i, p = await H.new_async(cb, st8)
    await H.send(i, "SWEEP_DUE", timeout=5)
    await H.quiesce(i, 15)
    n1 = len(st8.svc_calls)
    await H.quiesce(i, 15)
    n2 = len(st8.svc_calls)
    le = repr(i.last_error)
    ids9 = H.ids(i)
    await i.stop()
    rec("B19/rollback+onDone bounded (CV-221-01)",
        n1 == n2 and n1 <= 28 and "RunawayChainError" in le,
        json.dumps({"svc_t1": n1, "svc_t2": n2, "st": ids9,
                    "last_error": le[:120]}))


# ===================================================================== B20 ==
async def b20():
    c = H.cfg("B20")
    GV = {"breaches_daily_loss_cap": False, "within_warning_band": False,
          "outside_warning_band": False, "until_mode_is_time_based": True,
          "owner_and_elevated_and_override_permitted": True}
    o = await H.drive(c, S(c, guard_vals=dict(GV)), ["PNL_UPDATE"])
    rec("B20/happy stays clear",
        leaves(o) == ["clear"] and o["snapshot_ok"],
        json.dumps({"st": o["states"], "snap": o["snapshot_ok"]}))

    # INV-B20-a: breach locks and halts BEFORE alerting/broadcasting
    st = S(c, guard_vals=dict(GV, breaches_daily_loss_cap=True))
    o2 = await H.drive(c, st, ["PNL_UPDATE"])
    a = o2["actions"]
    rec("B20/INV-a breach -> locked, halt precedes broadcast",
        leaves(o2) == ["locked"]
        and a.index("halt_new_orders") < a.index("broadcast_lockout"),
        json.dumps({"st": o2["states"], "acts": a}))

    # INV-B20-b: warning band is visible and reversible
    st3 = S(c, guard_vals=dict(GV, within_warning_band=True))
    o3 = await H.drive(c, st3, ["PNL_UPDATE"])
    rec("B20/INV-b warning band visible",
        leaves(o3) == ["warning"] and "emit_risk_warning" in o3["actions"],
        json.dumps({"st": o3["states"]}))

    # INV-B20-c: expiry only in time-based mode
    st4 = S(c, guard_vals=dict(GV, breaches_daily_loss_cap=True,
                               until_mode_is_time_based=False))
    o4 = await H.drive(c, st4, ["PNL_UPDATE", "EXPIRY_DUE"])
    rec("B20/INV-c manual mode ignores EXPIRY_DUE",
        leaves(o4) == ["locked"]
        and "log_expiry_ignored_manual_mode" in o4["actions"],
        json.dumps({"st": o4["states"]}))
    st5 = S(c, guard_vals=dict(GV, breaches_daily_loss_cap=True))
    o5 = await H.drive(c, st5, ["PNL_UPDATE", "EXPIRY_DUE"])
    rec("B20/INV-c time mode resumes",
        leaves(o5) == ["clear"] and "resume_new_orders" in o5["actions"],
        json.dumps({"st": o5["states"]}))

    # INV-B20-d: override requires owner+elevation, both outcomes audited
    st6 = S(c, guard_vals=dict(GV, breaches_daily_loss_cap=True,
                               owner_and_elevated_and_override_permitted=False))
    o6 = await H.drive(c, st6, ["PNL_UPDATE", "OVERRIDE_REQUESTED"])
    rec("B20/INV-d override denied + audited",
        leaves(o6) == ["locked"] and "audit_override_denied" in o6["actions"],
        json.dumps({"st": o6["states"]}))

    # rollback: a raising alert must not leave trading resumed
    st7 = S(c, guard_vals=dict(GV, breaches_daily_loss_cap=True),
            raising=["raise_lockout_alert"])
    o7 = await H.drive(c, st7, ["PNL_UPDATE"])
    rec("B20/rollback keeps trading halted-or-clear consistently",
        leaves(o7) == ["clear"] and "broadcast_lockout" not in o7["actions"],
        json.dumps({"st": o7["states"], "acts": o7["actions"]}))

    so = H.drive_sync(c, S(c, guard_vals=dict(GV, breaches_daily_loss_cap=True)),
                      ["PNL_UPDATE"])
    rec("B20/sync parity", so["states"] == ["risk_lockout.locked"],
        json.dumps({"st": so["states"], "err": so["error"]}))


async def main():
    await b18()
    await b18_priority()
    await b19()
    await b20()
    H.dump("results/p2_b18_b20.json")


asyncio.run(main())
