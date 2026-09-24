# -*- coding: utf-8 -*-
"""D6 (round-10 new ground): our deadline actions as `raise(delay=)` timers.

B11 `schedule_linger_deadline` -> LINGER_DUE, B13 `schedule_backoff_deadline`
-> BACKOFF_DUE / `arm_pong_deadline` -> PONG_DEADLINE, B13
`schedule_budget_recheck` -> BUDGET_RECHECK, B14 `request_snapshot` ->
SNAPSHOT_TIMEOUT. In the catalogue these are opaque named actions; the
natural wrapper implementation on 0.8.1 is a delayed self-raise. Round 10
changes what that MEANS twice:

  #212 -- arming ends the step's chain; the firing is a clock event. A
          self-paced deadline that re-arms itself is a periodic process,
          NOT a runaway, at ANY period.
  #213 -- an ARMED, UNFIRED delayed self-send is snapshot state
          (`scheduled_sends`, remaining delay + id) and `start()` re-arms it.

So every deadline in our charts is now (a) safe to re-arm and (b) expected
to survive a snapshot with its REMAINING time. Both are load-bearing for the
OMS: a linger deadline lost across a process restart parks a recorder
forever (the #213 shape exactly), and a pong/backoff deadline charged as
chain debt would have tripped `maxIterations` on a long-lived feed.
"""
from __future__ import annotations
import asyncio, json, logging
import cv78 as H
from cv78 import rec, dump, cfg, Stub, build, STYLE
from xstate_statemachine import (
    Interpreter, SyncInterpreter, OverflowPolicy, create_machine,
)
from xstate_statemachine.actions import raise_
from xstate_statemachine.clock import SimulatedClock

# B11 linger (ms), B13 pong/backoff/budget, B14 snapshot timeout.
DEADLINES = {
    "B11": ("schedule_linger_deadline", "LINGER_DUE", 30000),
    "B13": ("schedule_backoff_deadline", "BACKOFF_DUE", 500),
    "B14": ("request_snapshot", "SNAPSHOT_TIMEOUT", 5000),
}


def mk(bid, deadline_ms=None, extra_acts=None):
    """Build `bid` with its deadline action implemented as raise(delay=)."""
    c = cfg(bid)
    act, evt, ms = DEADLINES[bid]
    ms = deadline_ms if deadline_ms is not None else ms
    st = Stub(c, guard_vals=GV[bid])
    fired = []

    def arm(interp, ctx, e, ad):
        """The wrapper's deadline: a delayed self-raise with a stable id."""
        interp.raise_(raise_(evt, delay=ms), send_id="cv-%s" % evt)

    st.act_impl[act] = None  # replaced below by the ActionDefinition path
    return c, st, evt, ms, fired


GV = {
    "B11": {"reasons_remain": False, "position_open_for_symbol": False,
            "all_streams_healthy": True},
    "B13": {"connection_budget_exhausted": False, "is_private": False},
    "B14": {},
}


def patch_deadline(c, act, evt, ms, send_id):
    """Rewrite the named deadline ACTION into a built-in delayed raise.

    This is the wrapper transformation, applied to a deep copy of the
    corrected catalogue JSON -- the JSON on disk is never edited.
    """
    tgt = {"type": "raise", "params": {"event": evt, "delay": ms,
                                       "id": send_id}}

    def walk(n):
        for key in ("entry", "exit"):
            v = n.get(key)
            if v is None:
                continue
            lst = v if isinstance(v, list) else [v]
            n[key] = [tgt if x == act else x for x in lst]
        for s in (n.get("states") or {}).values():
            walk(s)

    walk(c)
    return c


class P(H.CvHooks):
    pass


async def run(bid, ms, script, snap_at=None, limit=None, svc=None):
    """Drive `bid` with its deadline as a raise(delay=). `script` is a list
    of event names or ('__TICK__', ms). Returns observations."""
    act, evt, default_ms = DEADLINES[bid]
    c = patch_deadline(cfg(bid), act, evt, ms, "cv-" + evt)
    if limit is not None:
        c["maxIterations"] = limit
    st = Stub(c, guard_vals=GV[bid], svc=svc)
    m = build(c, st)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=256,
                    overflow_policy=OverflowPolicy.RAISE)
    p = P(); i.use(p)
    await i.start()
    await H.quiesce(i, 3)
    snaps = []
    for step in script:
        if isinstance(step, tuple) and step[0] == "__TICK__":
            await i.clock.increment(step[1])
            await H.quiesce(i, 3)
        elif step == "__SNAP__":
            blob = i.get_persisted_snapshot()
            raw = json.loads(blob) if isinstance(blob, str) else blob
            snaps.append(raw)
        else:
            await H.send(i, step)
            await H.quiesce(i, 2)
    out = {"states": H.ids(i), "err": repr(i.error) if i.error else None,
           "last_error": repr(getattr(i, "last_error", None)),
           "fires": [t for t in p.transitions if evt in t],
           "n_fire": sum(1 for t in p.transitions if t.startswith(evt)),
           "snaps": snaps, "dropped": p.dropped}
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass
    return out, c, st


async def d6a_fires():
    """The deadline fires as a clock event, once, at its period."""
    for bid in ("B11", "B13"):
        pre = {"B11": ["REASON_ADDED", "REASON_REMOVED"],
               "B13": ["CONNECT", "SOCKET_CLOSED"]}[bid]
        o, _, _ = await run(bid, 30000, pre + [("__TICK__", 29000)])
        rec("D6a/%s/armed-not-fired-before-period" % bid, o["n_fire"] == 0,
            "states=%s fires=%s" % (o["states"], o["fires"]))
        o, _, _ = await run(bid, 30000, pre + [("__TICK__", 31000)])
        rec("D6a/%s/fires-at-period" % bid, o["n_fire"] == 1,
            "states=%s fires=%s" % (o["states"], o["fires"]))


async def d6b_212_periodic():
    """#212: a re-arming deadline is a periodic process at ANY period.

    B13 backing_off -> BACKOFF_DUE -> connecting -> (dial fails) ->
    backing_off ... is exactly the OMS reconnect loop. Under the #206 rule
    each arm was chain debt and this tripped `maxIterations`; under #212 it
    must run indefinitely regardless of period, including 1 ms.
    """
    for period in (1, 50):
        # The OMS reconnect loop only CYCLES if the dial keeps failing;
        # a succeeding dial reaches `live` and disarms. Fail `open_socket`
        # so every BACKOFF_DUE re-enters backing_off and re-arms. A failing
        # dial puts CONNECT straight into backing_off, so no SOCKET_CLOSED
        # is needed (and would be unhandled under onUnhandled: error).
        o, _, _ = await run(
            "B13", period,
            ["CONNECT"] + [("__TICK__", period)] * 40,
            limit=5, svc={"open_socket": RuntimeError("refused")})
        rec("D6b/B13/reconnect-loop/period=%dms/no-runaway" % period,
            o["err"] is None and "RunawayChainError" not in (o["last_error"] or ""),
            "limit=5 ticks=40 fires=%d err=%s last=%s states=%s" % (
                o["n_fire"], o["err"], o["last_error"][:60], o["states"]))
        rec("D6b/B13/reconnect-loop/period=%dms/kept-cycling" % period,
            o["n_fire"] >= 5,
            "fired %d times under maxIterations=5" % o["n_fire"])


async def d6c_213_snapshot():
    """#213: an armed, unfired deadline is in the v3 snapshot with its
    REMAINING delay, and `start()` re-arms it."""
    for bid, pre in (("B11", ["REASON_ADDED", "REASON_REMOVED"]),
                     ("B13", ["CONNECT", "SOCKET_CLOSED"])):
        act, evt, _ = DEADLINES[bid]
        o, c, st = await run(bid, 30000, pre + [("__TICK__", 10000), "__SNAP__"])
        raw = o["snaps"][0]
        sched = raw.get("scheduled_sends") or []
        rec("D6c/%s/v3-layout" % bid, raw.get("version") == 3,
            "version=%r" % raw.get("version"))
        rec("D6c/%s/armed-send-persisted" % bid, len(sched) == 1,
            "scheduled_sends=%s" % json.dumps(sched)[:200])
        if not sched:
            rec("D6c/%s/remaining-delay" % bid, False, "no record")
            rec("D6c/%s/restore-rearms-and-fires" % bid, False, "no record")
            continue
        r = sched[0]
        rem = r.get("delay") or r.get("remaining") or r.get("remaining_ms")
        rec("D6c/%s/remaining-delay-not-full-period" % bid,
            rem is not None and 19000 <= float(rem) <= 21000,
            "remaining=%r (armed 30000, 10000 elapsed -> expect ~20000)" % rem)
        # restore into a fresh machine and confirm the deadline still fires
        c2 = patch_deadline(cfg(bid), act, evt, 30000, "cv-" + evt)
        st2 = Stub(c2, guard_vals=GV[bid])
        m2 = build(c2, st2)
        j = Interpreter.from_snapshot(json.dumps(raw), m2,
                                      clock=SimulatedClock(),
                                      minimum_version=3)
        p2 = P(); j.use(p2)
        await j.start()
        await H.quiesce(j, 3)
        before = H.ids(j)
        await j.clock.increment(19000)
        await H.quiesce(j, 3)
        mid = H.ids(j)
        await j.clock.increment(2000)
        await H.quiesce(j, 3)
        after = H.ids(j)
        nf = sum(1 for t in p2.transitions if t.startswith(evt))
        rec("D6c/%s/restore-rearms-with-remaining" % bid,
            nf == 1 and mid == before and after != before,
            "restored=%s @+19s=%s @+21s=%s fires=%d" % (
                before, mid, after, nf))
        try:
            await asyncio.wait_for(j.stop(), 5)
        except Exception:
            pass


def d6d_sync_parity():
    """Sync engine: same deadline, same firing, same v3 record.

    Runs OUTSIDE any event loop -- `SimulatedClock.increment()` is the
    blocking spelling there; calling it inside a running loop warns and
    fires nothing.
    """
    bid, evt = "B11", "LINGER_DUE"
    c = patch_deadline(cfg(bid), DEADLINES[bid][0], evt, 30000, "cv-" + evt)
    st = Stub(c, guard_vals=GV[bid], sync=True)
    i = SyncInterpreter(build(c, st), clock=SimulatedClock())
    p = P(); i.use(p)
    i.start()
    i.send("REASON_ADDED"); i.send("REASON_REMOVED")
    blob = i.get_persisted_snapshot()
    raw = json.loads(blob) if isinstance(blob, str) else blob
    sched = raw.get("scheduled_sends") or []
    rec("D6d/B11/sync/armed-send-persisted",
        raw.get("version") == 3 and len(sched) == 1,
        "v=%r sched=%s" % (raw.get("version"), json.dumps(sched)[:160]))
    try:
        i.clock.increment(31000)
    except Exception as e:
        rec("D6d/B11/sync/tick", False, repr(e)[:100])
    nf = sum(1 for t in p.transitions if t.startswith(evt))
    rec("D6d/B11/sync/fires-at-period", nf == 1,
        "fires=%d states=%s" % (nf, H.ids(i)))
    try:
        i.stop()
    except Exception:
        pass


async def main():
    logging.disable(logging.CRITICAL)
    await d6a_fires()
    await d6b_212_periodic()
    await d6c_213_snapshot()


if __name__ == "__main__":
    asyncio.run(main())
    d6d_sync_parity()   # outside the loop -- see its docstring
    dump("h_d6_deadlines.json")
