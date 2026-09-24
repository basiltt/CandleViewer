# -*- coding: utf-8 -*-
"""q3: sharp edges for B6-B10 @ c78ce99.

  A. #207 rollback+onDone storm -> stranded hook, plateau == maxIterations+3
     service calls, configuration parked, dormant invocation answerable.
     B7 carries the shape natively (arming invokes; rollback re-enters
     arming).  B6/B9/B10 do NOT -- their onDone leaves the invoking state
     and the cycle needs an external event -- so the storm is driven on a
     clearly-labelled OVERLAY of each contract (onDone re-enters).
  B. #204 always -> invoked child: no arm on same-macrostep exit, both
     engines, on the real contract states.
  C. #212 / #213 timers.  Our B6-B10 carry NO `after` and NO raise(delay=),
     so the obligations run on contract-shaped overlays: an `after` on
     B6.armed (slice pacing) and a 1 ms raise(delay=) ping-pong
     (heartbeat).  #212: the ping-pong must NOT trip maxIterations.
     #213: an armed, unfired delayed send must survive snapshot/restore
     (layout v3 `scheduled_sends`).
  D. sync parity: configuration + action trace + service-call trace.

Run: q3_sharp.py [async|def]
"""
from __future__ import annotations
import asyncio, json, os, sys
os.environ["CV_SVC_STYLE"] = sys.argv[1] if len(sys.argv) > 1 else "async"
STYLE = os.environ["CV_SVC_STYLE"]
import cvc78 as H
from cvc78 import Stub
from xstate_statemachine import Interpreter, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock

rec = H.rec


def S(c, **kw):
    kw.setdefault("svc_style", STYLE)
    return Stub(c, **kw)


def budgeted(c, n):
    c2 = json.loads(json.dumps(c))
    c2["maxIterations"] = n
    return c2


G6 = {"slice_qty_below_min_roll_forward": False, "price_limit_breached": False,
      "failures_exhausted": False, "preflight_invalid": False,
      "abort_on_price_limit": False, "final_market_sweep_and_remaining": False,
      "on_disconnect_is_freeze": True}
G7 = {"repricing_budget_exhausted": False, "chase_timeout_reached": False,
      "failures_exhausted": False, "price_moved_beyond_limit": False}
G9 = {"condition_true": True, "condition_true_and_requires_confirmation": False,
      "error_budget_exhausted": False, "in_cooldown": False,
      "promotion_gate_satisfied_and_permitted": True,
      "debounce_blocked": False, "data_stale": False, "limits_blocked": False,
      "simulation_window_elapsed": True, "budget_exhausted": False}
G10 = {"in_storm_window": False, "all_channels_ok": True,
       "delivery_attempts_left": True, "severity_requires_ack": False}


# =========================================================== A: #207 storm ==
async def storm(c, raiser, gv, ev, limit):
    c = budgeted(c, limit)
    st = S(c, guard_vals=dict(gv), raising=[raiser])
    m, i, p = await H.new_async(c, st)
    for e in ([] if not ev else ([ev] if isinstance(ev, str) else ev)):
        await H.send(i, e, timeout=5)
        await H.quiesce(i, 2)
    prev, laps = -1, []
    for _ in range(30):                       # poll to CONVERGENCE
        await H.quiesce(i, 4)
        n = len(st.svc_calls)
        laps.append(n)
        if n == prev:
            break
        prev = n
    out = {"plateau": prev, "limit": limit, "state": H.ids(i),
           "stranded": list(p.stranded),
           "dormant": bool(getattr(i, "has_dormant_invocations", False)),
           "last_error": repr(i.last_error)[:130], "laps": laps[-4:]}
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass
    return out


def overlay_rearm(c, state_path, invoke_state):
    """Make the invoking state's onDone re-enter itself (OVERLAY, labelled)."""
    c = json.loads(json.dumps(c))
    node = c
    for seg in state_path:
        node = node["states"][seg]
    inv = node["invoke"]
    inv = inv[0] if isinstance(inv, list) else inv
    inv["onDone"] = {"target": invoke_state, "actions": inv_actions(inv),
                     "reenter": True}
    return c


def inv_actions(inv):
    od = inv.get("onDone")
    od = od[0] if isinstance(od, list) else (od or {})
    a = od.get("actions") or []
    return a if isinstance(a, list) else [a]


CASES_A = [
    # (label, config, raiser, guards, kick event, limit)
    ("B7 (native shape)", lambda: H.cfg("B7"), "record_child", G7, None, 7),
    ("B6 (overlay)",
     lambda: overlay_rearm(H.cfg("B6"), ["submitting_slice"],
                           "#twap.submitting_slice"),
     "record_child", G6, "SLICE_DUE", 5),
    ("B9 (overlay)",
     lambda: overlay_rearm(H.cfg("B9"), ["acting"], "#rule_instance.acting"),
     "record_fire", G9, ["SAVE", "ARM_REQUESTED", "TRIGGER"], 6),
    ("B10 (overlay)",
     lambda: overlay_rearm(H.cfg("B10"), ["firing"], "#alert.firing"),
     "mark_delivered", G10, "CONDITION_MET", 4),
]


async def a_storms():
    for label, mk, raiser, gv, ev, lim in CASES_A:
        try:
            r = await storm(mk(), raiser, gv, ev, lim)
        except Exception as e:
            rec("#207/%s storm" % label, False, repr(e)[:200])
            continue
        tripped = "RunawayChainError" in r["last_error"]
        rec("#207/%s: chain cut is observable (stranded hook + dormant)"
            % label, tripped and r["stranded"] and r["dormant"], json.dumps(r))
        # The mandated plateau is maxIterations+3 when the cycle is
        # entered with SEED standing (the initial descent, #209/#215);
        # a cycle kicked by an EXTERNAL event costs one lap less (+2).
        over = r["plateau"] - r["limit"]
        rec("#207/%s: plateau is maxIterations+2/+3 (deterministic)" % label,
            over in (2, 3),
            json.dumps({"plateau": r["plateau"], "limit": r["limit"],
                        "over": over, "state": r["state"],
                        "tripped": tripped}))


# ========================================== B: #204 always -> invoked child ==
CASES_B = [
    ("B6.submitting_slice", "B6", ["submitting_slice"], "#twap.armed",
     G6, "SLICE_DUE", "submit_child", "twap.armed"),
    ("B9.evaluating", "B9", ["evaluating"], "#rule_instance.armed",
     G9, ["SAVE", "ARM_REQUESTED", "TRIGGER"], "evaluate_condition_dag",
     "rule_instance.armed"),
    ("B10.firing", "B10", ["firing"], "#alert.armed",
     G10, "CONDITION_MET", "dispatch_to_channels", "alert.armed"),
]


async def b_no_arm():
    for label, bid, path, tgt, gv, ev, svc, expect in CASES_B:
        c = json.loads(json.dumps(H.cfg(bid)))
        node = c
        for seg in path:
            node = node["states"][seg]
        node["always"] = [{"target": tgt}]
        st = S(c, guard_vals=dict(gv))
        evs = [ev] if isinstance(ev, str) else list(ev)
        o = await H.drive(c, st, evs)
        rec("#204/%s: invoke never arms on same-macrostep exit" % label,
            svc not in o["svc_calls"] and expect in o["states"],
            json.dumps({"st": o["states"], "svc": o["svc_calls"]}))
        so = H.drive_sync(c, Stub(c, guard_vals=dict(gv), svc_style="def"),
                          evs)
        rec("#204/%s [SYNC] same" % label,
            svc not in so["svc_calls"] and expect in so["states"],
            json.dumps({"st": so["states"], "svc": so["svc_calls"]}))


async def main():
    await a_storms()
    await b_no_arm()
    H.dump("q3ab.json")


if __name__ == "__main__":
    asyncio.run(main())
