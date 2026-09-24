# -*- coding: utf-8 -*-
"""p4: the round-10 axis on the real control machines (c78ce99).

Our B16-B20 carry NO `after` and NO `raise(delay=)` (verified: zero hits).
So #212 (delayed self-send is a timer) and #213 (`scheduled_sends` survives a
snapshot) cannot be exercised by the charts as written. This driver tests them
on the shape we would actually ship: B20's expiry deadline, whose
`schedule_expiry_deadline` action the catalogue leaves to the wrapper, re-done
as a chart-level `after`, and as a `raise(delay=)` self-ping.

Checks:
  p4a  B20 + `after` expiry: fires on the SimulatedClock, resumes trading
  p4b  B20 + raise(delay=) self-ping heartbeat: runs past maxIterations beats
       (#212 -- under the OLD #206 rule this tripped RunawayChainError)
  p4c  snapshot WITH an armed, unfired delayed send: v3 carries it in
       `scheduled_sends`, restore re-arms it, and it still fires (#213)
  p4d  #214: a v2 payload is refused by minimum_version=3, and a forged
       user event in the restored inbox is refused by `strict`
       (on_invalid_event / last_error), not silently accepted.
Both service spellings.
"""
from __future__ import annotations
import asyncio, copy, json, os, sys

os.environ["CV_SVC_STYLE"] = sys.argv[1] if len(sys.argv) > 1 else "async"
STYLE = os.environ["CV_SVC_STYLE"]

import cvc78 as H
from cvc78 import Stub, CvHooks, build, ids
from xstate_statemachine import Interpreter, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import SnapshotVersionError


def S(c, **kw):
    kw.setdefault("svc_style", STYLE)
    return Stub(c, **kw)


async def mk(c, stub, maxq=64):
    m = build(c, stub)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=maxq,
                    overflow_policy=OverflowPolicy.RAISE)
    p = CvHooks()
    i.use(p)
    await i.start()
    await H.quiesce(i, 3)
    return m, i, p


async def tick(i, ms, n=3):
    await i.clock.increment(ms)
    await H.quiesce(i, n)


def b20_after(delay=5000):
    """B20 with the expiry deadline as a chart-level `after` on `locked`."""
    c = H.cfg("B20")
    c["states"]["locked"].setdefault("after", {})[delay] = {
        "target": "clear", "guard": "auto_expiry_mode"}
    return c


def b20_ping(delay=1, limit=5):
    """B20 with a 1 ms `raise(delay=)` self ping-pong on `locked`.

    Under #206 this was a debt of the arming step and tripped at
    `maxIterations` beats; under #212 it is a periodic process.
    """
    c = H.cfg("B20")
    c["maxIterations"] = limit
    c["states"]["locked"].setdefault("entry", [])
    e = c["states"]["locked"]["entry"]
    if not isinstance(e, list):
        e = c["states"]["locked"]["entry"] = [e]
    e.append({"type": "raise",
              "params": {"event": "PING", "delay": delay, "id": "beat"}})
    c["states"]["locked"].setdefault("on", {})["PING"] = {
        "target": "locked", "reenter": True, "actions": ["audit_lockout"]}
    return c


GV = {"breaches_daily_loss_cap": True, "until_mode_is_time_based": True,
      "auto_expiry_mode": True,
      "owner_and_elevated_and_override_permitted": True}


# ------------------------------------------------- p4a: `after` deadline --
async def p4a():
    c = b20_after(5000)
    st = S(c, guard_vals=dict(GV))
    m, i, p = await mk(c, st)
    await i.send("PNL_UPDATE")
    await H.quiesce(i, 3)
    locked = ids(i)
    await tick(i, 4999)
    before = ids(i)
    await tick(i, 2)
    after = ids(i)
    await i.stop()
    H.rec("p4a/B20 after-expiry fires on the clock, not early",
          locked == ["risk_lockout.locked"]
          and before == ["risk_lockout.locked"]
          and after == ["risk_lockout.clear"],
          json.dumps({"locked": locked, "t=4999": before, "t=5001": after,
                      "resumed": "resume_new_orders" in p.actions}))


# ------------------------------- p4b: #212 raise(delay=) heartbeat lives ---
async def p4b():
    LIMIT = 5
    c = b20_ping(delay=1, limit=LIMIT)
    st = S(c, guard_vals=dict(GV))
    m, i, p = await mk(c, st)
    await i.send("PNL_UPDATE")
    await H.quiesce(i, 3)
    beats = []
    for _ in range(3 * LIMIT):          # 15 ms of clock => >> maxIterations
        await tick(i, 1, n=2)
        beats.append(st.trace.count("audit_lockout"))
    err = repr(i.error) if i.error else None
    status = i.status
    await i.stop()
    n = beats[-1]
    grew = n > LIMIT + 3 and beats[-1] > beats[len(beats) // 2]
    H.rec("p4b/#212 raise(delay=) heartbeat is a timer, not a chain",
          grew and err is None and status == "running",
          json.dumps({"limit": LIMIT, "beats": beats[-6:], "total": n,
                      "status": status, "error": err}))
    H.rec("p4b/#212 no RunawayChainError at maxIterations beats",
          err is None or "Runaway" not in err, json.dumps({"error": err}))


# ---------------------- p4c: #213 armed delayed send survives a snapshot --
async def p4c():
    """Two timers, same position, two different persistence contracts.

    subject   : `raise(delay=)` -- #213 says v3 carries it and `start()`
                re-arms it with the REMAINING delay, no opt-in.
    contrast  : `after` -- #128 says a deadline is NOT persisted; it is
                re-armed FROM ZERO only if the caller passes
                `restart_timers=True`. Recorded because our wrapper must
                know the two are not interchangeable.
    """
    # --- subject: raise(delay=) ------------------------------------
    c = b20_ping(delay=4000, limit=50)
    st = S(c, guard_vals=dict(GV))
    m, i, p = await mk(c, st)
    await i.send('PNL_UPDATE')
    await H.quiesce(i, 3)
    await tick(i, 1000)                 # 3000 ms still to run
    blob = i.get_persisted_snapshot()
    if isinstance(blob, dict):
        blob = json.dumps(blob)
    payload = json.loads(blob)
    sched = payload.get('scheduled_sends')
    await i.stop()

    st2 = S(c, guard_vals=dict(GV))
    j = Interpreter.from_snapshot(blob, build(c, st2), clock=SimulatedClock(),
                                  minimum_version=3)
    await j.start()
    await H.quiesce(j, 4)
    b0 = st2.trace.count('audit_lockout')
    await tick(j, 2999, n=4)
    b_early = st2.trace.count('audit_lockout')
    await tick(j, 2, n=4)
    b_late = st2.trace.count('audit_lockout')
    await j.stop()
    H.rec('p4c/#213 v3 carries the armed raise(delay=) with remaining_ms',
          isinstance(sched, list) and len(sched) == 1
          and abs(float(sched[0].get('remaining_ms', 0)) - 3000.0) < 1.0,
          json.dumps({'version': payload.get('version'), 'sched': sched}))
    H.rec('p4c/#213 restore re-arms it at the REMAINING delay, not from zero',
          b0 == 0 and b_early == 0 and b_late >= 1,
          json.dumps({'t0': b0, 't+2999': b_early, 't+3001': b_late}))

    # --- contrast: `after` is NOT persisted (#128, opt-in from zero) ---
    ca = b20_after(5000)
    sa = S(ca, guard_vals=dict(GV))
    m2, i2, p2 = await mk(ca, sa)
    await i2.send('PNL_UPDATE')
    await H.quiesce(i2, 3)
    await tick(i2, 1000)                # 4000 ms notionally left
    blob2 = i2.get_persisted_snapshot()
    if isinstance(blob2, dict):
        blob2 = json.dumps(blob2)
    sched2 = json.loads(blob2).get('scheduled_sends')
    await i2.stop()
    # default restore: deadline gone, state parked
    ja = Interpreter.from_snapshot(blob2, build(ca, S(ca, guard_vals=dict(GV))),
                                   clock=SimulatedClock(), minimum_version=3)
    await ja.start()
    await H.quiesce(ja, 3)
    await tick(ja, 50000, n=4)
    parked = ids(ja)
    dormant_default = getattr(ja, 'has_dormant_timers', None)
    await ja.stop()
    # opt-in restore: re-armed FROM ZERO
    jb = Interpreter.from_snapshot(blob2, build(ca, S(ca, guard_vals=dict(GV))),
                                   clock=SimulatedClock(), restart_timers=True)
    await jb.start()
    await H.quiesce(jb, 3)
    await tick(jb, 4000, n=4)
    at_remaining = ids(jb)             # would have fired if remaining were kept
    await tick(jb, 1100, n=4)
    at_full = ids(jb)
    await jb.stop()
    H.rec('p4c/#128 `after` is absent from v3 scheduled_sends (by design)',
          sched2 == [], json.dumps({'sched': sched2}))
    H.rec('p4c/#128 default restore parks the `after` state forever',
          parked == ['risk_lockout.locked'],
          json.dumps({'after_50s': parked, 'has_dormant_timers': dormant_default}))
    H.rec('p4c/#128 restart_timers=True re-arms it FROM ZERO (wrapper duty)',
          at_remaining == ['risk_lockout.locked']
          and at_full == ['risk_lockout.clear'],
          json.dumps({'t+4000_remaining': at_remaining,
                      't+5100_full': at_full}))

# --------------------------------------- p4d: #214 strict restore path ----
async def p4d():
    c = b20_after(5000)
    st = S(c, guard_vals=dict(GV))
    m, i, p = await mk(c, st)
    await i.send("PNL_UPDATE")
    await H.quiesce(i, 3)
    blob = i.get_persisted_snapshot()
    if isinstance(blob, dict):
        blob = json.dumps(blob)
    await i.stop()
    payload = json.loads(blob)

    # (1) a v2 downgrade is refused when the caller demands v3
    v2 = copy.deepcopy(payload)
    v2["version"] = 2
    v2.pop("scheduled_sends", None)
    refused = None
    try:
        Interpreter.from_snapshot(json.dumps(v2), build(c, S(c, guard_vals=dict(GV))),
                                  clock=SimulatedClock(), minimum_version=3)
    except SnapshotVersionError as e:
        refused = repr(e)
    except Exception as e:
        refused = "WRONG:" + repr(e)
    H.rec("p4d/#205+#214 v2 downgrade refused at minimum_version=3",
          refused is not None and not refused.startswith("WRONG"),
          json.dumps({"refused": refused}))

    # (2) a forged USER event in the restored inbox meets `strict`
    forged = copy.deepcopy(payload)
    forged.setdefault("pending_events", []).append(
        {"type": "NOT_A_REAL_EVENT", "payload": {}})
    m3 = build(c, S(c, guard_vals=dict(GV)))
    p3 = CvHooks()
    bad = None
    try:
        k = Interpreter.from_snapshot(json.dumps(forged), m3,
                                      clock=SimulatedClock())
        k.use(p3)
        await k.start()
        await H.quiesce(k, 3)
        state = ids(k)
        last = repr(k.error) if k.error else None
        await k.stop()
    except Exception as e:
        bad = repr(e)
        state, last = None, None
    H.rec("p4d/#214 forged restored event meets strict (refused, not run)",
          bad is not None or state == ["risk_lockout.locked"],
          json.dumps({"raised": bad, "state": state, "error": last,
                      "invalid_hook": getattr(p3, "invalid", None),
                      "dropped": p3.dropped}))


async def main():
    await p4a()
    await p4b()
    await p4c()
    await p4d()
    H.dump("results/p4_timers.json")


asyncio.run(main())
