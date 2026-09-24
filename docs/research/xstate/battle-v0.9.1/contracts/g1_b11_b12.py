# -*- coding: utf-8 -*-
"""G1: B11 RecordingSession + B12 ReplaySession end-to-end on v0.9.0.

Happy path, invariants, rollback, defer star-lane, guard raise,
snapshot/restore at every quiescence (chain_trips asserted 0 + preserved,
plugins= on every restore).
STANDALONE: stdlib + xstate_statemachine only, neutral cwd.
"""
from __future__ import annotations
import asyncio, os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cv9 as K  # noqa: E402
os.chdir("C:/Users/basil")


def b11_stub(c, **kw):
    gv = {
        "reasons_remain": lambda ctx, e: len(ctx.get("reasons") or []) > 0,
        "all_streams_healthy": lambda ctx, e: all(
            (ctx.get("streams_healthy") or {}).values()),
        "position_open_for_symbol": False,
    }
    gv.update(kw.pop("guard_vals", {}))
    impl = {
        "add_reason": lambda i, ctx, e, a: ctx["reasons"].append(
            getattr(e, "payload", {}).get("reason", "r")),
        "remove_reason": lambda i, ctx, e, a: (
            ctx["reasons"].pop() if ctx["reasons"] else None),
        "mark_stream_unhealthy": lambda i, ctx, e, a: ctx[
            "streams_healthy"].__setitem__(
            getattr(e, "payload", {}).get("stream", "s1"), False),
        "mark_stream_healthy": lambda i, ctx, e, a: ctx[
            "streams_healthy"].__setitem__(
            getattr(e, "payload", {}).get("stream", "s1"), True),
        "bump_gap_count": lambda i, ctx, e, a: ctx.__setitem__(
            "gap_count_24h", ctx["gap_count_24h"] + 1),
    }
    impl.update(kw.pop("act_impl", {}))
    return K.Stub(c, guard_vals=gv, act_impl=impl, **kw)


def _bad(notes):
    return "; ".join(n for n in notes if "drift" in n or "DRIFT" in n
                     or "raised" in n or "refused" in n
                     or "NONZERO" in n or "not wired" in n)[:300]


async def b11_happy():
    c = K.cfg("B11")
    st = b11_stub(c)
    r = await K.drive(c, st, [
        ("REASON_ADDED", {"reason": "user"}),
        ("STREAM_UNHEALTHY", {"stream": "trades"}),
        ("STREAM_HEALTHY", {"stream": "trades"}),
        ("GAP_DETECTED", {}),
        ("REASON_REMOVED", {}),
        ("LINGER_DUE", {}),
    ])
    K.rec("G1.B11.happy.lands_stopped",
          r["states"] == ["recording.stopped"],
          "states=%s ctx=%s" % (r["states"], r["context"]))
    K.rec("G1.B11.happy.snapshot_ok", r["snapshot_ok"], _bad(r["notes"]))
    K.rec("G1.B11.happy.chain_trips_zero", r["chain_trips"] == 0,
          "trips=%r lce=%r" % (r["chain_trips"], r["last_chain_error"]))
    K.rec("G1.B11.happy.no_fatal",
          r["status"] == "running" and r["error"] is None,
          "status=%s err=%s" % (r["status"], r["error"]))
    K.rec("G1.B11.inv.gap_counted", r["context"]["gap_count_24h"] == 1,
          "gap=%r" % r["context"]["gap_count_24h"])
    K.rec("G1.B11.inv.both_services_ran",
          r["svc_calls"] == ["subscribe_streams", "unsubscribe_and_flush"],
          "svc=%s" % r["svc_calls"])
    K.rec("G1.B11.inv.degraded_alert_once",
          r["actions"].count("raise_degraded_alert") == 1,
          "acts=%s" % r["actions"])


async def b11_rollback():
    c = K.cfg("B11")
    st = b11_stub(c, raising=("emit_recording_metric",))
    r = await K.drive(c, st, [("REASON_ADDED", {"reason": "user"})],
                      snapshots=False)
    K.rec("G1.B11.rollback.reported", len(r["action_errors"]) >= 1,
          "action_errors=%s states=%s" % (r["action_errors"][:2], r["states"]))
    K.rec("G1.B11.rollback.context_intact",
          r["context"]["gap_count_24h"] == 0, "ctx=%s" % r["context"])
    K.rec("G1.B11.rollback.no_fatal", r["status"] == "running",
          "status=%s err=%s" % (r["status"], r["error"]))


async def b11_service_error():
    c = K.cfg("B11")
    st = b11_stub(c, svc={"subscribe_streams": RuntimeError("no socket")})
    r = await K.drive(c, st, [("REASON_ADDED", {"reason": "user"})],
                      snapshots=False)
    K.rec("G1.B11.onError.lands_error", r["states"] == ["recording.error"],
          "states=%s" % r["states"])
    r2 = await K.drive(c, b11_stub(c),
                       [("REASON_ADDED", {"reason": "u"}),
                        ("STREAM_UNHEALTHY", {"stream": "t"})])
    K.rec("G1.B11.degraded.snapshot_ok", r2["snapshot_ok"], _bad(r2["notes"]))


async def b11_guard_raise():
    c = K.cfg("B11")
    st = b11_stub(c, guard_raise=("reasons_remain",))
    r = await K.drive(c, st, [("REASON_ADDED", {"reason": "u"}),
                              ("REASON_REMOVED", {})], snapshots=False)
    K.rec("G1.B11.guard_raise.surfaced",
          len(r["guard_errors"]) >= 1 or r["error"] is not None,
          "guard_errors=%s err=%s states=%s"
          % (r["guard_errors"][:2], r["error"], r["states"]))


async def b12_happy():
    c = K.cfg("B12")
    gv = {"loop_enabled": lambda ctx, e: bool(ctx.get("loop"))}
    impl = {
        "set_cursor": lambda i, ctx, e, a: ctx.__setitem__(
            "cursor", ctx["cursor"] + 1),
        "set_speed": lambda i, ctx, e, a: ctx.__setitem__(
            "speed", getattr(e, "payload", {}).get("speed", 2.0)),
    }
    st = K.Stub(c, guard_vals=gv, act_impl=impl)
    r = await K.drive(c, st, ["PREPARE", "PLAY", ("SET_SPEED", {"speed": 4.0}),
                              "CONSUMER_SLOW", "PAUSE", "STEP", "PLAY",
                              "RANGE_END"])
    K.rec("G1.B12.happy.lands_finished",
          r["states"] == ["replay.finished"], "states=%s" % r["states"])
    K.rec("G1.B12.happy.snapshot_ok", r["snapshot_ok"], _bad(r["notes"]))
    K.rec("G1.B12.happy.chain_trips_zero", r["chain_trips"] == 0,
          "trips=%r" % r["chain_trips"])
    K.rec("G1.B12.inv.clock_paired",
          r["actions"].count("start_clock") == r["actions"].count("stop_clock"),
          "start=%d stop=%d" % (r["actions"].count("start_clock"),
                                r["actions"].count("stop_clock")))
    K.rec("G1.B12.inv.speed_applied", r["context"]["speed"] == 4.0,
          "speed=%r" % r["context"]["speed"])
    K.rec("G1.B12.inv.cursor_advanced", r["context"]["cursor"] >= 2,
          "cursor=%r" % r["context"]["cursor"])


async def b12_star_defer():
    c = K.cfg("B12")
    slow = asyncio.Event()

    async def hold(i, ctx, e):
        await slow.wait()
        return {"cursor": 7}

    st = K.Stub(c, guard_vals={"loop_enabled": False},
                svc={"seek_and_prime": hold})
    m, i, p = await K.new_async(c, st)
    await K.send(i, "PREPARE")
    await K.quiesce(i, 2)
    mid = K.ids(i)
    await K.send(i, "SET_SPEED", timeout=3.0, speed=3.0)
    await K.quiesce(i, 2)
    dc = i.deferred_count
    slow.set()
    await K.quiesce(i, 4)
    K.rec("G1.B12.star.buffering_reached", mid == ["replay.buffering"],
          "mid=%s" % mid)
    K.rec("G1.B12.star.deferred_then_drained", K.ids(i) == ["replay.paused"],
          "deferred_while_buffering=%r after=%s drain=%d"
          % (dc, K.ids(i), p.actions.count("drain_deferred")))
    K.rec("G1.B12.star.no_drop", not p.dropped, "dropped=%s" % (p.dropped,))
    await asyncio.wait_for(i.stop(), 5)


async def b12_destroy_final():
    c = K.cfg("B12")
    st = K.Stub(c, guard_vals={"loop_enabled": False})
    r = await K.drive(c, st, ["PREPARE", "DESTROY"])
    K.rec("G1.B12.final.destroyed", r["states"] == ["replay.destroyed"],
          "states=%s status=%s" % (r["states"], r["status"]))
    K.rec("G1.B12.final.snapshot_ok", r["snapshot_ok"], _bad(r["notes"]))


async def main():
    for fn in (b11_happy, b11_rollback, b11_service_error, b11_guard_raise,
               b12_happy, b12_star_defer, b12_destroy_final):
        try:
            await asyncio.wait_for(fn(), 60)
        except Exception as e:
            K.rec("G1.%s.EXC" % fn.__name__, False, repr(e)[:300])
    K.dump("res_g1_b11_b12.json")


asyncio.run(main())
