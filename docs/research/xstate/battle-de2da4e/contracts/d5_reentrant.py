# -*- coding: utf-8 -*-
"""D5 (de2da4e): #219 on a REAL catalogue chart.

B13 `live.entry` runs `arm_pong_deadline` and `PONG` runs
`rearm_pong_deadline`. If we had implemented either as "await my own
`send(..., wait=True)`" -- the obvious way to write "re-arm and be sure it
landed" -- c78ce99 deadlocked; de2da4e raises `ReentrantWaitError`.

Three lanes:
  (a) BAD shape  -> must raise ReentrantWaitError, not hang (async + sync).
  (b) rollback   -> the refusal is an action error, so `actionErrorPolicy:
                    rollback` must leave the chart in a sane state.
  (c) GOOD shape -> fire-and-forget (`ensure_future`, awaited later) still
                    works, which is the wrapper our contract should use.
"""
from __future__ import annotations
import asyncio, json
import cvb as H
from xstate_statemachine import Interpreter, SyncInterpreter, OverflowPolicy
from xstate_statemachine.exceptions import ReentrantWaitError
from xstate_statemachine.clock import SimulatedClock

GV = {"connection_budget_exhausted": False, "is_private": False}
WATCHDOG = 20.0


def b13():
    return H.cfg("B13")


async def bad_async():
    """`rearm_pong_deadline` awaits its own send(wait=True)."""
    c = b13()
    seen = {}

    async def rearm(i, ctx, e, ad):
        #: the tempting shape: "re-arm and be sure it landed".
        return await i.send("PONG", wait=True)

    st = H.Stub(c, guard_vals=GV, act_impl={"rearm_pong_deadline": rearm},
                act_async=["rearm_pong_deadline"])
    m, i, p = await H.new_async(c, st)
    r = await H.send(i, "CONNECT", timeout=WATCHDOG)
    await H.quiesce(i, 2)
    r2 = await H.send(i, "PONG", timeout=WATCHDOG)
    await H.quiesce(i, 3)
    hung = r2.get("timeout")
    errs = p.action_errors
    raised = any("ReentrantWaitError" in e for e in errs)
    H.rec("D5/219/async/reentrant-wait-refused", raised and not hung,
          "hung=%s action_errors=%s" % (hung, errs[:2]))
    H.rec("D5/219/async/rollback-keeps-chart-live",
          H.ids(i) == ["ws_conn.live"] and i.status == "running",
          "states=%s status=%s (actionErrorPolicy=rollback)"
          % (H.ids(i), i.status))
    H.rec("D5/219/async/no-chain-trip-from-refusal", i.chain_trips == 0,
          "chain_trips=%d" % i.chain_trips)
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass


def bad_sync():
    """Sync engine refuses the same shape for parity."""
    c = b13()

    def rearm(i, ctx, e, ad):
        return i.send("PONG", wait=True)

    st = H.Stub(c, guard_vals=GV, act_impl={"rearm_pong_deadline": rearm},
                svc_style="def")
    m, i, p = H.new_sync(c, st)
    i.send("CONNECT")
    exc = None
    try:
        i.send("PONG")
    except Exception as e:
        exc = e
    refused = any("ReentrantWaitError" in e for e in p.action_errors) or \
        isinstance(exc, ReentrantWaitError)
    H.rec("D5/219/sync/reentrant-wait-refused", refused,
          "raised=%r action_errors=%s" % (exc, p.action_errors[:2]))
    H.rec("D5/219/sync/parity-with-async", refused and i.status == "running",
          "states=%s status=%s" % (H.ids(i), i.status))
    try:
        i.stop()
    except Exception:
        pass


async def good_async():
    """The wrapper our contract SHOULD use: hand the receipt out, await it
    outside the step. Must still work on de2da4e."""
    c = b13()
    box = {"fut": None}

    def rearm(i, ctx, e, ad):
        box["fut"] = asyncio.ensure_future(i.send("SOCKET_CLOSED", wait=True))

    st = H.Stub(c, guard_vals=GV, act_impl={"rearm_pong_deadline": rearm},
                act_async=["rearm_pong_deadline"])
    m, i, p = await H.new_async(c, st)
    await H.send(i, "CONNECT", timeout=WATCHDOG)
    await H.quiesce(i, 2)
    r = await H.send(i, "PONG", timeout=WATCHDOG)
    await H.quiesce(i, 3)
    ok_recv = False
    try:
        await asyncio.wait_for(box["fut"], 10)
        ok_recv = True
    except Exception as e:
        ok_recv = "unhandled" in repr(e).lower()
    H.rec("D5/219/async/deferred-receipt-still-works",
          not r.get("timeout") and box["fut"] is not None,
          "PONG returned in %.3fs, receipt future=%s resolved=%s"
          % (r.get("sec", -1), box["fut"] is not None, ok_recv))
    H.rec("D5/219/async/good-shape-stays-live",
          H.ids(i) == ["ws_conn.backing_off"],
          "deferred SOCKET_CLOSED receipt resolved -> %s" % (H.ids(i),))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass


async def main():
    await bad_async()
    await good_async()


bad_sync()
asyncio.run(main())
H.dump("results/d5_reentrant.json")
