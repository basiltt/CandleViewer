# -*- coding: utf-8 -*-
"""G3: B13 ExchangeConnection + B14 IngestionPipeline + B15 PaperMatcher
end-to-end on v0.9.0/main.

B13: reconnect ladder, budget block, `*`->defer in subscribing, onUnhandled
error policy, snapshot/restore. B14: always->snapshot_pending, reenter:true
self-transition, delta buffering. B15: always->final liquidation.
STANDALONE: stdlib + xstate_statemachine only, neutral cwd.
"""
from __future__ import annotations
import asyncio, os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv9 as K  # noqa: E402
from g1_b11_b12 import _bad  # noqa: E402
os.chdir("<home>")


# ------------------------------------------------------------------ B13 ---
def b13_stub(c, private=False, budget=False, **kw):
    gv = {"is_private": private, "connection_budget_exhausted": budget}
    gv.update(kw.pop("guard_vals", {}))
    impl = {"bump_attempt": lambda i, ctx, e, a: ctx.__setitem__(
        "attempt", ctx["attempt"] + 1),
        "reset_backoff": lambda i, ctx, e, a: ctx.__setitem__("attempt", 0)}
    impl.update(kw.pop("act_impl", {}))
    return K.Stub(c, guard_vals=gv, act_impl=impl, **kw)


async def b13_public_happy():
    c = K.cfg("B13")
    st = b13_stub(c)
    r = await K.drive(c, st, ["CONNECT", "PONG", "SOCKET_CLOSED",
                              "BACKOFF_DUE", "SHUTDOWN"])
    K.rec("G3.B13.happy.lands_closed", r["states"] == ["ws_conn.closed"],
          "states=%s status=%s" % (r["states"], r["status"]))
    K.rec("G3.B13.happy.snapshot_ok", r["snapshot_ok"], _bad(r["notes"]))
    K.rec("G3.B13.happy.chain_trips_zero", r["chain_trips"] == 0,
          "trips=%r" % r["chain_trips"])
    K.rec("G3.B13.inv.public_skips_auth", "ws_auth" not in r["svc_calls"],
          "svc=%s" % r["svc_calls"])
    # The script reconnects once (SOCKET_CLOSED -> backing_off ->
    # BACKOFF_DUE -> connecting -> live), so `live` is entered TWICE and
    # reset_backoff must run once per entry.
    K.rec("G3.B13.inv.backoff_reset_per_live_entry",
          r["actions"].count("reset_backoff")
          == r["actions"].count("emit_feed_healthy") == 2,
          "reset=%d healthy=%d" % (r["actions"].count("reset_backoff"),
                                   r["actions"].count("emit_feed_healthy")))
    K.rec("G3.B13.inv.degraded_notified",
          r["actions"].count("notify_dependents_degraded") == 1,
          "n=%d" % r["actions"].count("notify_dependents_degraded"))


async def b13_private_auth():
    c = K.cfg("B13")
    st = b13_stub(c, private=True)
    r = await K.drive(c, st, ["CONNECT"], snapshots=False)
    K.rec("G3.B13.private.auth_ran",
          r["svc_calls"][:3] == ["open_socket", "ws_auth",
                                 "subscribe_in_batches"],
          "svc=%s states=%s" % (r["svc_calls"], r["states"]))
    K.rec("G3.B13.private.reaches_live", r["states"] == ["ws_conn.live"],
          "states=%s" % r["states"])


async def b13_budget_blocked():
    c = K.cfg("B13")
    st = b13_stub(c, budget=True)
    r = await K.drive(c, st, ["CONNECT", "BUDGET_RECHECK"])
    K.rec("G3.B13.budget.blocked_then_recheck",
          r["states"] == ["ws_conn.disconnected"]
          and r["actions"].count("raise_conn_budget_alert") == 1,
          "states=%s acts=%s" % (r["states"], r["actions"]))
    K.rec("G3.B13.budget.no_socket_opened", "open_socket" not in r["svc_calls"],
          "svc=%s" % r["svc_calls"])
    K.rec("G3.B13.budget.snapshot_ok", r["snapshot_ok"], _bad(r["notes"]))


async def b13_auth_error_backoff():
    c = K.cfg("B13")
    st = b13_stub(c, private=True, svc={"ws_auth": RuntimeError("401")})
    r = await K.drive(c, st, ["CONNECT"], snapshots=False)
    K.rec("G3.B13.auth_error.backs_off",
          r["states"] == ["ws_conn.backing_off"]
          and "record_auth_error" in r["actions"],
          "states=%s acts=%s" % (r["states"], r["actions"]))
    K.rec("G3.B13.auth_error.no_fatal", r["status"] == "running",
          "status=%s err=%s" % (r["status"], r["error"]))


async def b13_star_defer_in_subscribing():
    """subscribing has `*`->defer; onUnhandled is `error` at root, so an
    event arriving there must be deferred, NOT fatal."""
    c = K.cfg("B13")
    hold = asyncio.Event()

    async def slow(i, ctx, e):
        await hold.wait()
        return {"ok": True}

    st = b13_stub(c, svc={"subscribe_in_batches": slow})
    m, i, p = await K.new_async(c, st)
    await K.send(i, "CONNECT")
    await K.quiesce(i, 3)
    mid = K.ids(i)
    await K.send(i, "PONG", timeout=3.0)
    await K.quiesce(i, 2)
    mid_status = i.status
    hold.set()
    await K.quiesce(i, 4)
    K.rec("G3.B13.star.subscribing_reached", mid == ["ws_conn.subscribing"],
          "mid=%s" % mid)
    K.rec("G3.B13.star.deferred_not_fatal", mid_status == "running",
          "status_while_subscribing=%s err=%s" % (mid_status, i.error))
    K.rec("G3.B13.star.drained_at_live", K.ids(i) == ["ws_conn.live"],
          "after=%s drain=%d acts_tail=%s"
          % (K.ids(i), p.actions.count("drain_deferred"), p.actions[-5:]))
    await asyncio.wait_for(i.stop(), 5)


# ------------------------------------------------------------------ B14 ---
def b14_stub(c, **kw):
    impl = {
        "buffer_delta": lambda i, ctx, e, a: ctx["buffered_deltas"].append(
            getattr(e, "payload", {}).get("seq", 0)),
        "clear_buffer": lambda i, ctx, e, a: ctx["buffered_deltas"].clear(),
        "install_snapshot": lambda i, ctx, e, a: ctx.__setitem__(
            "snapshot_seq", getattr(e, "payload", {}).get("seq", 10)),
        "apply_delta": lambda i, ctx, e, a: ctx.__setitem__(
            "last_seq", getattr(e, "payload", {}).get("seq", 0)),
        "bump_resync_count": lambda i, ctx, e, a: ctx.__setitem__(
            "resync_count", ctx["resync_count"] + 1),
    }
    impl.update(kw.pop("act_impl", {}))
    return K.Stub(c, act_impl=impl, **kw)


async def b14_happy():
    c = K.cfg("B14")
    st = b14_stub(c)
    r = await K.drive(c, st, ["SUBSCRIBE", ("DELTA", {"seq": 11}),
                              ("SNAPSHOT", {"seq": 10}),
                              ("DELTA", {"seq": 12})])
    K.rec("G3.B14.happy.live", r["states"] == ["book.live"],
          "states=%s ctx=%s" % (r["states"], r["context"]))
    K.rec("G3.B14.happy.snapshot_ok", r["snapshot_ok"], _bad(r["notes"]))
    K.rec("G3.B14.inv.buffered_then_replayed",
          "replay_buffered_deltas_after_seq" in r["actions"]
          and r["context"]["last_seq"] == 12,
          "acts=%s last_seq=%r" % (r["actions"], r["context"]["last_seq"]))
    K.rec("G3.B14.happy.chain_trips_zero", r["chain_trips"] == 0,
          "trips=%r" % r["chain_trips"])


async def b14_always_resync():
    """SEQUENCE_GAP -> desynced -> always -> snapshot_pending, in ONE
    macrostep, with the resync counter bumped exactly once."""
    c = K.cfg("B14")
    st = b14_stub(c)
    r = await K.drive(c, st, ["SUBSCRIBE", ("SNAPSHOT", {"seq": 10}),
                              ("SEQUENCE_GAP", {})])
    K.rec("G3.B14.always.transient_to_snapshot_pending",
          r["states"] == ["book.snapshot_pending"], "states=%s" % r["states"])
    K.rec("G3.B14.always.resync_counted_once",
          r["context"]["resync_count"] == 1,
          "resync=%r acts=%s" % (r["context"]["resync_count"], r["actions"]))
    K.rec("G3.B14.always.not_consumable_then_rerequest",
          r["actions"].count("request_snapshot") == 2
          and "emit_book_desynced" in r["actions"],
          "acts=%s" % r["actions"])
    K.rec("G3.B14.always.chain_trips_zero", r["chain_trips"] == 0,
          "trips=%r lce=%r" % (r["chain_trips"], r["last_chain_error"]))
    K.rec("G3.B14.always.snapshot_ok", r["snapshot_ok"], _bad(r["notes"]))


async def b14_reenter_self_transition():
    """SNAPSHOT_TIMEOUT has reenter:true -- entry actions must re-run."""
    c = K.cfg("B14")
    st = b14_stub(c)
    r = await K.drive(c, st, ["SUBSCRIBE", ("SNAPSHOT_TIMEOUT", {})],
                      snapshots=False)
    K.rec("G3.B14.reenter.entry_reran",
          r["actions"].count("request_snapshot") == 2,
          "request_snapshot=%d acts=%s"
          % (r["actions"].count("request_snapshot"), r["actions"]))
    K.rec("G3.B14.reenter.counter_bumped",
          r["context"]["resync_count"] == 1,
          "resync=%r" % r["context"]["resync_count"])


# ------------------------------------------------------------------ B15 ---
async def b15_liquidation():
    c = K.cfg("B15")
    st = K.Stub(c, guard_vals={"mark_crossed_liq_price": True,
                               "below_maintenance_margin": False,
                               "above_maintenance_margin": False})
    r = await K.drive(c, st, [("MARK_UPDATE", {})])
    K.rec("G3.B15.liq.reaches_final", r["states"] == ["paper_account.liquidated"],
          "states=%s status=%s" % (r["states"], r["status"]))
    K.rec("G3.B15.liq.journal_written",
          r["actions"].count("write_liquidation_journal") == 1
          and r["actions"].count("apply_liquidation_haircut") == 1,
          "acts=%s" % r["actions"])
    K.rec("G3.B15.liq.chain_trips_zero", r["chain_trips"] == 0,
          "trips=%r" % r["chain_trips"])
    K.rec("G3.B15.liq.snapshot_ok", r["snapshot_ok"], _bad(r["notes"]))


async def b15_margin_call_recovery():
    c = K.cfg("B15")
    flags = {"below": True, "above": False}
    st = K.Stub(c, guard_vals={
        "mark_crossed_liq_price": False,
        "below_maintenance_margin": lambda ctx, e: flags["below"],
        "above_maintenance_margin": lambda ctx, e: flags["above"]})
    m, i, p = await K.new_async(c, st)
    await K.send(i, "MARK_UPDATE")
    await K.quiesce(i, 2)
    mid = K.ids(i)
    flags["below"], flags["above"] = False, True
    await K.send(i, "MARK_UPDATE")
    await K.quiesce(i, 2)
    K.rec("G3.B15.margin.warns_then_recovers",
          mid == ["paper_account.margin_call"]
          and K.ids(i) == ["paper_account.active"],
          "mid=%s end=%s warn=%d" % (mid, K.ids(i),
                                     p.actions.count("emit_margin_warning")))
    K.rec("G3.B15.margin.no_fatal", i.status == "running" and i.error is None,
          "status=%s err=%s" % (i.status, i.error))
    await asyncio.wait_for(i.stop(), 5)


# ---------------------------------------------------------------- sync ----
def sync_parity():
    for b, script, want in (
            ("B13", ["CONNECT", "PONG", "SOCKET_CLOSED", "BACKOFF_DUE",
                     "SHUTDOWN"], ["ws_conn.closed"]),
            ("B14", ["SUBSCRIBE", ("SNAPSHOT", {"seq": 10}),
                     ("SEQUENCE_GAP", {})], ["book.snapshot_pending"]),
            ("B15", [("MARK_UPDATE", {})], ["paper_account.liquidated"])):
        c = K.cfg(b)
        if b == "B13":
            st = b13_stub(c, sync=True)
        elif b == "B14":
            st = b14_stub(c, sync=True)
        else:
            st = K.Stub(c, sync=True, guard_vals={
                "mark_crossed_liq_price": True,
                "below_maintenance_margin": False,
                "above_maintenance_margin": False})
        r = K.drive_sync(c, st, script)
        K.rec("G3.%s.sync_parity" % b, r["states"] == want,
              "states=%s want=%s svc=%s" % (r["states"], want, r["svc_calls"]))
        K.rec("G3.%s.sync_chain_trips_zero" % b, r["chain_trips"] == 0,
              "trips=%r" % r["chain_trips"])


async def main():
    for fn in (b13_public_happy, b13_private_auth, b13_budget_blocked,
               b13_auth_error_backoff, b13_star_defer_in_subscribing,
               b14_happy, b14_always_resync, b14_reenter_self_transition,
               b15_liquidation, b15_margin_call_recovery):
        try:
            await asyncio.wait_for(fn(), 60)
        except Exception as e:
            K.rec("G3.%s.EXC" % fn.__name__, False, repr(e)[:300])
    try:
        sync_parity()
    except Exception as e:
        K.rec("G3.sync_parity.EXC", False, repr(e)[:300])
    K.dump("res_g3_b13_b15.json")


asyncio.run(main())
