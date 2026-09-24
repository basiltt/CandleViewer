# -*- coding: utf-8 -*-
"""B1 Order - end-to-end contract drive on 3ed3099 (async engine)."""
from __future__ import annotations
import asyncio, json, copy, os, sys
from xstate_statemachine import (Interpreter, OverflowPolicy, SnapshotMidStepError,
                                 SimulatedClock, create_machine)
import charness as H

VARIANT = os.environ.get("CV_VARIANT", "orig")
CFG = json.load(open("B1.%s.json" % ("orig" if VARIANT == "orig" else "machine"), encoding="utf-8"))
print("=== B1 variant:", VARIANT, "===")
R = {}


def rec(k, ok, note=""):
    R[k] = {"pass": bool(ok), "note": note}
    print(("PASS " if ok else "FAIL ") + k + ("  | " + note if note else ""))


def mk(guard_vals=None, svc=None, raising=(), **kw):
    st = H.Stub(CFG, guard_vals=guard_vals, svc=svc, raising=raising, **kw)
    return st, H.build(CFG, st)


async def new(stub, machine, maxq=None):
    i = Interpreter(machine, clock=SimulatedClock(), max_queue_size=maxq,
                    overflow_policy=OverflowPolicy.RAISE)
    p = H.TraceP()
    i.use(p)
    await i.start()
    await H.quiesce(i, 3)
    return i, p


def with_service(stub, name, fn):
    logic = stub.logic()
    logic.services[name] = fn
    return create_machine(copy.deepcopy(CFG), logic=logic)


# --------------------------------------------------------------- S1 happy --
async def s1_happy():
    st, m = mk(guard_vals={"passes_all_gates": True, "ret_code_ok": True,
                           "exec_new_and_closes": True},
               svc={"place_order": {"retCode": 0}})
    i, p = await new(st, m)
    rec("B1/init", H.ids(i) == ["order.lifecycle.draft", "order.protection.not_required"],
        str(H.ids(i)))
    await i.send("VALIDATE")
    await H.quiesce(i, 2)
    await i.send("SEND")
    await H.quiesce(i, 5)
    rec("B1/happy-submitted", "order.lifecycle.submitted" in H.ids(i), str(H.ids(i)))
    await i.send("EXEC", exec_id="e1")
    await H.quiesce(i, 3)
    rec("B1/happy-filled", "order.lifecycle.filled" in H.ids(i), str(H.ids(i)))
    before = H.ids(i)
    try:
        await i.send("CANCEL")
    except Exception:
        pass
    await H.quiesce(i, 2)
    rec("B1/INV-2-terminal-sticky", H.ids(i) == before,
        str(before) + " -> " + str(H.ids(i)) + "; unhandled=" + str(p.unhandled[-2:]))
    await i.stop()


# ---------------------------------------------- S2 fill during submitting --
async def s2_fill_during_submitting():
    gate = asyncio.Event()

    async def slow_place(interp, ctx, evt):
        await gate.wait()
        return {"retCode": 0}

    st = H.Stub(CFG, guard_vals={"passes_all_gates": True, "ret_code_ok": True,
                                 "exec_new_and_closes": True})
    m = with_service(st, "place_order", slow_place)
    i, p = await new(st, m)
    await i.send("VALIDATE")
    await H.quiesce(i, 2)
    await i.send("SEND")
    await H.quiesce(i, 3)
    assert "order.lifecycle.submitting" in H.ids(i), H.ids(i)
    r = await i.send("EXEC", exec_id="e1", wait=True)
    await H.quiesce(i, 2)
    held = i.deferred_count
    star = st.trace.count("defer")
    rec("B1/INV-5-exec-held-by-runtime", held == 1,
        "deferred_count=%s, inline '*' defer action fired %sx, receipt deferred=%s changed=%s"
        % (held, star, getattr(r, "deferred", None), getattr(r, "changed", None)))
    R["_b1_receipt_defer"] = {"deferred": getattr(r, "deferred", None),
                              "changed": getattr(r, "changed", None),
                              "error": repr(getattr(r, "error", None))}
    gate.set()
    await H.quiesce(i, 6)
    rec("B1/INV-5-exec-applied-after-ack",
        "order.lifecycle.filled" in H.ids(i) and "apply_fill" in st.trace,
        "ids=%s apply_fill=%s tail=%s" % (H.ids(i), "apply_fill" in st.trace, st.trace[-6:]))
    await i.stop()


# -------------------------------------------------- S3 reject / rollback ---
async def s3_reject_rollback():
    st, m = mk(guard_vals={"passes_all_gates": True, "ret_code_ok": False,
                           "is_duplicate_link_id": False},
               svc={"place_order": {"retCode": 110007}})
    i, p = await new(st, m)
    await i.send("VALIDATE")
    await H.quiesce(i, 2)
    await i.send("SEND")
    await H.quiesce(i, 6)
    rec("B1/reject-path", "order.lifecycle.rejected" in H.ids(i),
        "%s trace=%s" % (H.ids(i), st.trace[-4:]))
    await i.stop()


async def s3b_action_rollback():
    st, m = mk(guard_vals={"passes_all_gates": True}, raising=("stamp_validated",))
    i, p = await new(st, m)
    before = H.ids(i)
    r = await i.send("VALIDATE", wait=True)
    await H.quiesce(i, 3)
    rec("B1/rollback-no-halfcommit", H.ids(i) == before,
        "%s -> %s; receipt.error=%r" % (before, H.ids(i), getattr(r, "error", None)))
    await i.stop()


# ------------------------------------------------------------ protection --
async def s4_protection():
    st, m = mk(guard_vals={"passes_all_gates": True, "ret_code_ok": True},
               svc={"attach_native_sl": RuntimeError("no sl")})
    i, p = await new(st, m)
    await i.send("FIRST_FILL")
    await H.quiesce(i, 5)
    rec("B1/B8-sl-attach-failure-is-naked",
        "order.protection.sl_missing" in H.ids(i), str(H.ids(i)))
    await i.send("SL_OBSERVED")
    await H.quiesce(i, 2)
    rec("B1/INV-B1-f-sl-present-only-from-read",
        "order.protection.sl_present" in H.ids(i), str(H.ids(i)))
    await i.stop()


async def s4b_structural_gate():
    """B8: is any lifecycle transition gated on the protection region?"""
    txt = json.dumps(CFG)
    gated = ("stateIn" in txt) or ("in" in CFG.get("states", {}))
    rec("B1/B8-structural-gate-present", gated,
        "no stateIn/in guard anywhere in B1 JSON: the lifecycle region can reach "
        "partially_filled/filled while protection is sl_missing - the B8 invariant is "
        "observable but not enforced by this machine")


# ------------------------------------------------------- amend / recon ----
async def s5_amend_rejected():
    gate = asyncio.Event()

    async def hang(interp, ctx, evt):
        await gate.wait()
        return {}

    st = H.Stub(CFG, guard_vals={"passes_all_gates": True, "ret_code_ok": True,
                                 "exec_new_and_partial": True, "has_fills": True},
                svc={"place_order": {"retCode": 0}})
    m = with_service(st, "amend_order", hang)
    i, p = await new(st, m)
    await i.send("VALIDATE")
    await H.quiesce(i, 2)
    await i.send("SEND")
    await H.quiesce(i, 5)
    await i.send("EXEC", exec_id="e1")
    await H.quiesce(i, 3)
    assert "order.lifecycle.partially_filled" in H.ids(i), H.ids(i)
    await i.send("AMEND")
    await H.quiesce(i, 3)
    await i.send("AMEND_REJECTED")
    await H.quiesce(i, 4)
    rec("B1/INV-B1-c-amend-rejected-keeps-order-live",
        "order.lifecycle.partially_filled" in H.ids(i),
        "%s (deferred=%s)" % (H.ids(i), i.deferred_count))
    gate.set()
    await H.quiesce(i, 2)
    await i.stop()


async def s5b_fill_beats_cancel():
    """INV-B1-d: EXEC in cancel_pending is handled, not deferred."""
    gate = asyncio.Event()

    async def hang(interp, ctx, evt):
        await gate.wait()
        return {}

    st = H.Stub(CFG, guard_vals={"passes_all_gates": True, "ret_code_ok": True,
                                 "exec_new_and_closes": True},
                svc={"place_order": {"retCode": 0}})
    m = with_service(st, "cancel_order", hang)
    i, p = await new(st, m)
    await i.send("VALIDATE")
    await H.quiesce(i, 2)
    await i.send("SEND")
    await H.quiesce(i, 5)
    await i.send("CANCEL")
    await H.quiesce(i, 3)
    assert "order.lifecycle.cancel_pending" in H.ids(i), H.ids(i)
    await i.send("EXEC", exec_id="e9")
    await H.quiesce(i, 4)
    rec("B1/INV-B1-d-fill-beats-cancel",
        "order.lifecycle.filled" in H.ids(i),
        "%s deferred=%s" % (H.ids(i), i.deferred_count))
    gate.set()
    await H.quiesce(i, 3)
    rec("B1/INV-2-late-cancel-ack-cannot-revive",
        "order.lifecycle.filled" in H.ids(i),
        "after cancel_order resolved: %s" % (H.ids(i),))
    await i.stop()


async def s6_unknown_recon():
    st, m = mk(guard_vals={"passes_all_gates": True,
                           "second_consecutive_miss":
                               lambda c, e: int(c.get("recon_misses") or 0) >= 1},
               svc={"place_order": ConnectionError("transport")},
               act_impl={"bump_recon_misses":
                         lambda i, c, e, a: c.__setitem__(
                             "recon_misses", int(c.get("recon_misses") or 0) + 1)})
    i, p = await new(st, m)
    await i.send("VALIDATE")
    await H.quiesce(i, 2)
    await i.send("SEND")
    await H.quiesce(i, 6)
    rec("B1/B13-transport-fault-to-unknown", "order.lifecycle.unknown" in H.ids(i),
        "%s record_transport_fault=%s" % (H.ids(i), "record_transport_fault" in st.trace))
    n_place = st.svc_calls.count("place_order")
    await i.send("RECON_MISS")
    await H.quiesce(i, 3)
    rec("B1/INV-B1-e-unknown-never-resubmits",
        st.svc_calls.count("place_order") == n_place and "order.lifecycle.unknown" in H.ids(i),
        "place_order %s->%s ids=%s misses=%s"
        % (n_place, st.svc_calls.count("place_order"), H.ids(i), i.context.get("recon_misses")))
    await i.send("RECON_MISS")
    await H.quiesce(i, 3)
    rec("B1/B19-second-miss-unresolvable", "order.lifecycle.rejected" in H.ids(i),
        "%s misses=%s" % (H.ids(i), i.context.get("recon_misses")))
    await i.stop()


async def s6b_recon_found_partial():
    st, m = mk(guard_vals={"passes_all_gates": True},
               svc={"place_order": ConnectionError("transport")})
    i, p = await new(st, m)
    await i.send("VALIDATE")
    await H.quiesce(i, 2)
    await i.send("SEND")
    await H.quiesce(i, 6)
    await i.send("RECON_FOUND_PARTIAL")
    await H.quiesce(i, 3)
    rec("B1/B19-recon-divergence-partial",
        "order.lifecycle.partially_filled" in H.ids(i), str(H.ids(i)))
    await i.stop()


# ------------------------------------------- B18 kill switch / priority ----
async def s7_priority_preempt():
    gate = asyncio.Event()

    async def slow(interp, ctx, evt):
        await gate.wait()
        return {"retCode": 0}

    st = H.Stub(CFG, guard_vals={"passes_all_gates": True, "ret_code_ok": True})
    m = with_service(st, "place_order", slow)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=4,
                    overflow_policy=OverflowPolicy.RAISE)
    p = H.TraceP()
    i.use(p)
    await i.start()
    await H.quiesce(i, 2)
    await i.send("VALIDATE")
    await H.quiesce(i, 2)
    await i.send("SEND")
    await H.quiesce(i, 3)
    assert "order.lifecycle.submitting" in H.ids(i), H.ids(i)
    overflowed = 0
    for n in range(12):
        try:
            await i.send("EXEC", exec_id="x%d" % n)
        except Exception:
            overflowed += 1
    ok_prio, err = True, ""
    try:
        await i.send_priority("FAULT")
    except Exception as e:
        ok_prio = False
        err = "%s: %s" % (type(e).__name__, e)
    gate.set()
    await H.quiesce(i, 8)
    rec("B1/B18-priority-accepted-on-full-inbox", ok_prio,
        "overflow raises=%s, send_priority err=%r" % (overflowed, err))
    rec("B1/B18-priority-preempts-backlog",
        "order.lifecycle.quarantined" in H.ids(i),
        "ids after drain=%s dropped=%s" % (H.ids(i), p.dropped[:3]))
    await i.stop()


# --------------------------------------- snapshot at every quiescent point -
SCRIPT = [("VALIDATE", {}), ("SEND", {}), ("EXEC", {"exec_id": "e1"}),
          ("FIRST_FILL", {}), ("SL_OBSERVED", {}), ("CANCEL", {})]


def _mk_for_script():
    return H.Stub(CFG, guard_vals={"passes_all_gates": True, "ret_code_ok": True,
                                   "exec_new_and_partial": True},
                  svc={"place_order": {"retCode": 0},
                       "cancel_order": {"ok": True},
                       "attach_native_sl": {"ok": True}})


async def drive(i, start, stop):
    for n in range(start, stop):
        ev, pay = SCRIPT[n]
        try:
            await i.send(ev, **pay)
        except Exception:
            pass
        await H.quiesce(i, 3)


async def s8_snapshot_parity():
    st = _mk_for_script()
    ref_i, _ = await new(st, H.build(CFG, st))
    await drive(ref_i, 0, len(SCRIPT))
    ref_ids = H.ids(ref_i)
    ref_ctx = json.loads(json.dumps(ref_i.context, default=str))
    ref_trace = list(st.trace)
    await ref_i.stop()

    midstep, mismatch, trace_diff = [], [], []
    for k in range(len(SCRIPT) + 1):
        st1 = _mk_for_script()
        i1, _ = await new(st1, H.build(CFG, st1))
        await drive(i1, 0, k)
        try:
            blob = json.dumps(i1.get_persisted_snapshot())
        except SnapshotMidStepError as e:
            midstep.append((k, str(e)[:90]))
            await i1.stop()
            continue
        pre = list(st1.trace)
        await i1.stop()

        st2 = _mk_for_script()
        i2 = Interpreter.from_snapshot(blob, H.build(CFG, st2), clock=SimulatedClock(),
                                       restart_services=True, restart_timers=True)
        i2.use(H.TraceP())
        await i2.start()
        await H.quiesce(i2, 4)
        await drive(i2, k, len(SCRIPT))
        got_ids = H.ids(i2)
        got_ctx = json.loads(json.dumps(i2.context, default=str))
        if got_ids != ref_ids or got_ctx != ref_ctx:
            mismatch.append((k, got_ids, {kk: (got_ctx.get(kk), ref_ctx.get(kk))
                                          for kk in ref_ctx if got_ctx.get(kk) != ref_ctx.get(kk)}))
        full = pre + st2.trace
        if full != ref_trace:
            trace_diff.append((k, len(full), len(ref_trace),
                               [a for a in full if a not in ref_trace][:4]))
        await i2.stop()

    rec("B1/snapshot-never-midstep-at-quiescence", not midstep, "refusals at k=%s" % (midstep,))
    rec("B1/snapshot-resume-state-parity", not mismatch,
        ("ref=%s" % (ref_ids,)) if not mismatch else "mismatch=%s" % (mismatch,))
    rec("B1/snapshot-resume-action-trace-parity", not trace_diff,
        "len(ref_trace)=%d diffs=%s" % (len(ref_trace), trace_diff))


async def main():
    for f in (s1_happy, s2_fill_during_submitting, s3_reject_rollback,
              s3b_action_rollback, s4_protection, s4b_structural_gate,
              s5_amend_rejected, s5b_fill_beats_cancel, s6_unknown_recon,
              s6b_recon_found_partial, s7_priority_preempt, s8_snapshot_parity):
        try:
            await f()
        except Exception as e:
            import traceback
            traceback.print_exc()
            rec("B1/%s-CRASH" % f.__name__, False, "%s: %s" % (type(e).__name__, e))
    json.dump(R, open("b1_order.%s.json" % VARIANT, "w", encoding="utf-8"), indent=1)


asyncio.run(main())
