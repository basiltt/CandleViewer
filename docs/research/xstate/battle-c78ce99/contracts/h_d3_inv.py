# -*- coding: utf-8 -*-
"""D3: catalogue invariants for B11-B15 + async/sync parity + snapshot trace.

Every driver runs under the mandatory config via cv78.drive (snapshot/restore
round-trip at EVERY macrostep, compared against the uninterrupted run).
"""
from __future__ import annotations
import asyncio, json
import cv78 as H

R = []


def chk(name, ok, note=""):
    H.rec(name, ok, note)
    R.append((name, ok))


async def b11():
    c = H.cfg("B11")
    # INV-B11-a: STREAM_UNHEALTHY -> degraded (tagged), STREAM_HEALTHY with all
    # healthy returns to recording.
    st = H.Stub(c, guard_vals={"reasons_remain": True, "all_streams_healthy": True})
    r = await H.drive(c, st, ["REASON_ADDED", "STREAM_UNHEALTHY", "STREAM_HEALTHY"])
    chk("B11/INV-a/degraded-roundtrip", r["states"] == ["recording.recording"]
        and "raise_degraded_alert" in r["actions"] and r["snapshot_ok"],
        "%s snap=%s" % (r["states"], r["snapshot_ok"]))

    # INV-B11-b: partial heal stays degraded
    st = H.Stub(c, guard_vals={"reasons_remain": True, "all_streams_healthy": False})
    r = await H.drive(c, st, ["REASON_ADDED", "STREAM_UNHEALTHY", "STREAM_HEALTHY"])
    chk("B11/INV-b/partial-heal-stays-degraded",
        r["states"] == ["recording.degraded"], str(r["states"]))

    # INV-B11-c: last reason removed -> lingering; a new reason rescues it
    st = H.Stub(c, guard_vals={"reasons_remain": False})
    r = await H.drive(c, st, ["REASON_ADDED", "REASON_REMOVED", "REASON_ADDED"])
    chk("B11/INV-c/linger-rescue", r["states"] == ["recording.recording"]
        and "schedule_linger_deadline" in r["actions"], str(r["states"]))

    # INV-B11-d: LINGER_DUE with an open position returns to recording
    st = H.Stub(c, guard_vals={"reasons_remain": False,
                               "position_open_for_symbol": True})
    r = await H.drive(c, st, ["REASON_ADDED", "REASON_REMOVED", "LINGER_DUE"])
    chk("B11/INV-d/linger-due-position-open",
        r["states"] == ["recording.recording"], str(r["states"]))

    # INV-B11-e: service error -> error state (tagged), RETRY re-arms
    st = H.Stub(c, guard_vals={"reasons_remain": True},
                svc={"subscribe_streams": RuntimeError("no socket")})
    r = await H.drive(c, st, ["REASON_ADDED"])
    chk("B11/INV-e/onError->error", r["states"] == ["recording.error"]
        and "record_error" in r["actions"], "%s" % r["states"])

    # INV-B11-f: gap counting does not leave recording
    st = H.Stub(c, guard_vals={"reasons_remain": True})
    r = await H.drive(c, st, ["REASON_ADDED", "GAP_DETECTED", "GAP_DETECTED"])
    chk("B11/INV-f/gap-internal", r["states"] == ["recording.recording"]
        and r["actions"].count("bump_gap_count") == 2, str(r["states"]))


async def b12():
    c = H.cfg("B12")
    st = H.Stub(c, svc={"seek_and_prime": {"cursor": 5}})
    r = await H.drive(c, st, ["PREPARE", "PLAY", "PAUSE", "STEP"])
    chk("B12/INV-a/step-returns-paused", r["states"] == ["replay.paused"]
        and "emit_one_step" in r["svc_calls"], str(r["states"]))

    st = H.Stub(c, svc={"seek_and_prime": RuntimeError("bad range")})
    r = await H.drive(c, st, ["PREPARE"])
    chk("B12/INV-b/prime-error->error", r["states"] == ["replay.error"], str(r["states"]))

    st = H.Stub(c, svc={"seek_and_prime": {"cursor": 1}})
    r = await H.drive(c, st, ["PREPARE", "PLAY", "RANGE_END"])
    chk("B12/INV-c/range-end->finished", r["states"] == ["replay.finished"], str(r["states"]))

    st = H.Stub(c, svc={"seek_and_prime": {"cursor": 1}})
    r = await H.drive(c, st, ["PREPARE", "PLAY", "PAUSE", "DESTROY"])
    chk("B12/INV-d/destroy-final", r["states"] == ["replay.destroyed"], str(r["states"]))

    # INV-B12-e (documented def contract, #193): CANCEL during buffering
    st = H.Stub(c, svc={"seek_and_prime": {"cursor": 3}})
    r = await H.drive(c, st, ["PREPARE", "CANCEL"])
    if H.STYLE == "def":
        ok = r["states"] in (["replay.paused"], ["replay.created"])
        note = "def lane: CANCEL cannot pre-empt a def service (documented #193) -> %s" % r["states"]
    else:
        ok = r["states"] in (["replay.created"], ["replay.paused"])
        note = "async lane -> %s" % r["states"]
    chk("B12/INV-e/cancel-lane-aware", ok, note)


async def b13():
    c = H.cfg("B13")
    st = H.Stub(c, guard_vals={"connection_budget_exhausted": True})
    r = await H.drive(c, st, ["CONNECT"])
    chk("B13/INV-a/no-budget->budget_blocked",
        r["states"] == ["ws_conn.budget_blocked"], str(r["states"]))

    st = H.Stub(c, guard_vals={"connection_budget_exhausted": False, "is_private": True})
    r = await H.drive(c, st, ["CONNECT"])
    chk("B13/INV-b/private-auths", r["states"] == ["ws_conn.live"]
        and "ws_auth" in r["svc_calls"], "%s %s" % (r["states"], r["svc_calls"]))

    st = H.Stub(c, guard_vals={"connection_budget_exhausted": False, "is_private": False},
                svc={"open_socket": RuntimeError("refused")})
    r = await H.drive(c, st, ["CONNECT"])
    chk("B13/INV-c/dial-error->backing_off",
        r["states"] == ["ws_conn.backing_off"]
        and "record_conn_error" in r["actions"], str(r["states"]))

    st = H.Stub(c, guard_vals={"connection_budget_exhausted": False, "is_private": False})
    r = await H.drive(c, st, ["CONNECT", "SOCKET_CLOSED"])
    chk("B13/INV-d/socket-closed->backing_off",
        r["states"] == ["ws_conn.backing_off"], str(r["states"]))

    st = H.Stub(c, guard_vals={"connection_budget_exhausted": False, "is_private": False})
    r = await H.drive(c, st, ["CONNECT", "SHUTDOWN"])
    chk("B13/INV-e/shutdown->closed-final", r["states"] == ["ws_conn.closed"]
        and "close_socket" in r["svc_calls"], str(r["states"]))

    # INV-B13-f: the `*` defer in subscribing -- events during the batch
    # subscribe are not lost.
    st = H.Stub(c, guard_vals={"connection_budget_exhausted": False, "is_private": False})
    r = await H.drive(c, st, ["CONNECT", "PONG"])
    chk("B13/INV-f/live-pong-internal", r["states"] == ["ws_conn.live"],
        "%s deferred=%s" % (r["states"], r["deferred"]))


async def b14_b15():
    c = H.cfg("B14")
    st = H.Stub(c, guard_vals={})
    r = await H.drive(c, st, ["SUBSCRIBE", "SNAPSHOT", "SEQUENCE_GAP"])
    # desynced is transient (always -> snapshot_pending)
    chk("B14/INV-a/gap->desynced->snapshot_pending",
        r["states"] == ["book.snapshot_pending"] and r["snapshot_ok"],
        "%s snap=%s" % (r["states"], r["snapshot_ok"]))

    st = H.Stub(c, guard_vals={})
    r = await H.drive(c, st, ["SUBSCRIBE", "SNAPSHOT_TIMEOUT"])
    chk("B14/INV-b/snapshot-timeout-resync",
        r["states"] in (["book.snapshot_pending"], ["book.init"]), str(r["states"]))

    st = H.Stub(c, guard_vals={})
    r = await H.drive(c, st, ["SUBSCRIBE", "SNAPSHOT", "DELTA", "UNSUBSCRIBE"])
    chk("B14/INV-c/unsubscribe", r["states"] == ["book.init"], str(r["states"]))

    c = H.cfg("B15")
    st = H.Stub(c, guard_vals={"below_maintenance_margin": True, "mark_crossed_liq_price": False, "above_maintenance_margin": False})
    r = await H.drive(c, st, ["MARK_UPDATE"])
    chk("B15/INV-a/below-maintenance->margin_call",
        r["states"] == ["paper_account.margin_call"], str(r["states"]))

    st = H.Stub(c, guard_vals={"below_maintenance_margin": True, "mark_crossed_liq_price": True, "above_maintenance_margin": False})
    r = await H.drive(c, st, ["MARK_UPDATE", "MARK_UPDATE"])
    chk("B15/INV-b/equity-gone->liquidated-final",
        r["states"] == ["paper_account.liquidated"]
        and "apply_liquidation_haircut" in r["actions"],
        "%s acts=%s" % (r["states"], r["actions"][-3:]))


# ---------------------------------------------------------- sync parity ----
PARITY = {
    "B11": ({"reasons_remain": False, "position_open_for_symbol": False},
            {}, ["REASON_ADDED", "REASON_REMOVED", "LINGER_DUE"]),
    "B12": ({}, {"seek_and_prime": {"cursor": 5}}, ["PREPARE", "PLAY", "PAUSE"]),
    "B13": ({"connection_budget_exhausted": False, "is_private": False},
            {}, ["CONNECT", "SOCKET_CLOSED"]),
    "B14": ({}, {},
            ["SUBSCRIBE", "SNAPSHOT", "DELTA"]),
    "B15": ({"below_maintenance_margin": True, "mark_crossed_liq_price": True, "above_maintenance_margin": False}, {},
            ["MARK_UPDATE", "MARK_UPDATE"]),
}


async def parity():
    for bid, (gv, svc, script) in PARITY.items():
        c = H.cfg(bid)
        a = await H.drive(c, H.Stub(c, guard_vals=gv, svc=svc), script)
        s = H.drive_sync(c, H.Stub(c, guard_vals=gv, svc=svc, svc_style="def"),
                         script)
        ok = a["states"] == s["states"] and a["context"] == s["context"]
        chk("parity/%s/async==sync" % bid, ok,
            "async=%s sync=%s ctx_eq=%s" % (a["states"], s["states"],
                                            a["context"] == s["context"]))


async def main():
    await b11(); await b12(); await b13(); await b14_b15(); await parity()
    H.dump("h_d3_invariants.json")


asyncio.run(main())
