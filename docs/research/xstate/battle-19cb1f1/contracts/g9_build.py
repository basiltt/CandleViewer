# -*- coding: utf-8 -*-
"""B11-B15 @ 19cb1f1 -- build, policy plumbing, happy paths. Both lanes."""
from __future__ import annotations
import asyncio, json
import cv19 as H

BS = ["B11", "B12", "B13", "B14", "B15"]
POLICY = ["actionErrorPolicy", "onUnhandled", "guardErrorPolicy",
          "strictTargets", "strict", "spawnBlockingTimeout"]


def build_report():
    out = {}
    for b in BS:
        c = H.cfg(b)
        r = {"id": c["id"], "policy": {k: c.get(k) for k in POLICY if k in c}}
        st = H.Stub(c)
        try:
            m = H.build(c, st)
            r["stub_logic"] = "OK"
            r["attrs"] = {
                "action_error_policy": getattr(m, "action_error_policy", "?"),
                "on_unhandled": getattr(m, "on_unhandled", "?"),
                "guard_error_policy": getattr(m, "guard_error_policy", "?"),
                "strict_targets": getattr(m, "strict_targets", "?"),
                "strict": getattr(m, "strict", "?"),
                "spawn_blocking_timeout_ms": getattr(
                    m, "spawn_blocking_timeout_ms", "ABSENT"),
            }
            ok = (r["attrs"]["action_error_policy"] == "rollback"
                  and r["attrs"]["guard_error_policy"] == "raise"
                  and r["attrs"]["strict_targets"] is True
                  and r["attrs"]["spawn_blocking_timeout_ms"] == 5000.0)
            H.rec("%s/build" % b, ok, json.dumps(r["attrs"], default=str))
        except Exception as e:
            r["stub_logic"] = repr(e)
            H.rec("%s/build" % b, False, repr(e))
        out[b] = r
    return out


def bad_values():
    """Bad values for known keys must be refused; unknown keys are the gap."""
    from xstate_statemachine import create_machine, MachineLogic
    from xstate_statemachine.exceptions import InvalidConfigError
    base = {"id": "bv", "initial": "a", "states": {"a": {}}}
    for key, val in [("onUnhandled", "deferr"),
                     ("actionErrorPolicy", "rolback"),
                     ("guardErrorPolicy", "riase")]:
        c = dict(base, **{key: val})
        try:
            create_machine(c, logic=MachineLogic(strict=True))
            H.rec("cfg/bad-value/%s" % key, False, "ACCEPTED silently")
        except InvalidConfigError as e:
            H.rec("cfg/bad-value/%s" % key, True, type(e).__name__)
        except Exception as e:
            H.rec("cfg/bad-value/%s" % key, False, repr(e))
    # unknown key -- carry-forward NEEDS-WRAPPER check
    c = dict(base, spawnBlockingTimeoutMs=1234)
    m = create_machine(c, logic=MachineLogic(strict=True))
    got = getattr(m, "spawn_blocking_timeout_ms", "ABSENT")
    H.rec("cfg/unknown-key-diagnosed", False,
          "misspelled key accepted silently; effective=%r (NEEDS-WRAPPER)" % (got,))


# ------------------------------------------------------------- happy paths --
async def happy():
    # B11: idle -> starting -(sub done)-> recording -> REASON_REMOVED ->
    #      lingering -> LINGER_DUE(no position) -> stopping -> stopped
    c = H.cfg("B11")
    st = H.Stub(c, guard_vals={"reasons_remain": False,
                               "position_open_for_symbol": False,
                               "all_streams_healthy": True})
    r = await H.drive(c, st, ["REASON_ADDED", "REASON_REMOVED", "LINGER_DUE"])
    ok = r["states"] == ["recording.stopped"] and r["snapshot_ok"]
    H.rec("B11/happy", ok, "%s snap=%s svc=%s" % (
        r["states"], r["snapshot_ok"], r["svc_calls"]))

    # B12: created -PREPARE-> buffering -(prime done)-> paused -PLAY-> playing
    c = H.cfg("B12")
    st = H.Stub(c, svc={"seek_and_prime": {"cursor": 10}})
    r = await H.drive(c, st, ["PREPARE", "PLAY"])
    ok = r["states"] == ["replay.playing"] and r["snapshot_ok"]
    H.rec("B12/happy", ok, "%s snap=%s" % (r["states"], r["snapshot_ok"]))

    # B13: disconnected -CONNECT-> connecting -> authenticating -> subscribing -> live
    c = H.cfg("B13")
    st = H.Stub(c, guard_vals={"connection_budget_exhausted": False, "is_private": False})
    r = await H.drive(c, st, ["CONNECT"])
    ok = r["states"] == ["ws_conn.live"] and r["snapshot_ok"]
    H.rec("B13/happy", ok, "%s snap=%s svc=%s" % (
        r["states"], r["snapshot_ok"], r["svc_calls"]))

    # B14: init -SUBSCRIBE-> snapshot_pending -SNAPSHOT-> live
    c = H.cfg("B14")
    st = H.Stub(c, guard_vals={})
    r = await H.drive(c, st, ["SUBSCRIBE", "SNAPSHOT", "DELTA"])
    ok = r["states"] == ["book.live"] and r["snapshot_ok"]
    H.rec("B14/happy", ok, "%s snap=%s" % (r["states"], r["snapshot_ok"]))

    # B15: active -MARK_UPDATE(solvent)-> active
    c = H.cfg("B15")
    st = H.Stub(c, guard_vals={"below_maintenance_margin": False, "mark_crossed_liq_price": False})
    r = await H.drive(c, st, ["MARK_UPDATE"])
    ok = r["states"] == ["paper_account.active"] and r["snapshot_ok"]
    H.rec("B15/happy", ok, "%s snap=%s" % (r["states"], r["snapshot_ok"]))


def main():
    rep = build_report()
    bad_values()
    asyncio.run(happy())
    (H.HERE / ("g9_build_report.%s.json" % H.STYLE)).write_text(
        json.dumps(rep, indent=1, default=str), encoding="utf-8")
    H.dump("g9_build.json")


main()
