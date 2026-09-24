# -*- coding: utf-8 -*-
"""Round-11 obligations (#218,#219,#221,#222) on B6-B10 contract shapes."""
from __future__ import annotations
import asyncio, copy, json, os, sys
os.environ["CV_SVC_STYLE"] = sys.argv[1] if len(sys.argv) > 1 else "async"
STYLE = os.environ["CV_SVC_STYLE"]
import cvde as H
from cvde import Stub, cfg, rec, build, ids
from xstate_statemachine import Interpreter, SyncInterpreter, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock
import xstate_statemachine.exceptions as X


def heartbeat(b, up, down, period=1):
    """OVERLAY: 1 ms raise(delay=) ping-pong (the T2 shape, which is the
    shape #218 is about), reachable from the chart's start state."""
    c = copy.deepcopy(cfg(b))
    mid = c["id"]
    arm = {"type": "raise", "params": {"event": "BEAT", "delay": period}}
    # root-level handler: reachable from whatever state the chart settles in
    c.setdefault("on", {})["POLL_START"] = {"target": "#%s.%s" % (mid, up)}
    c["states"][up] = {"entry": [arm, "_beat"],
                       "on": {"BEAT": {"target": "#%s.%s" % (mid, down)}}}
    c["states"][down] = {"entry": [arm, "_beat"],
                         "on": {"BEAT": {"target": "#%s.%s" % (mid, up)}}}
    c["x-overlay"] = "heartbeat ping-pong on %s" % b
    return c


async def t218():
    """A long raise(delay=) heartbeat holds at most one clock handle."""
    for b in ("B6", "B10"):
        c = heartbeat(b, "poll_up", "poll_down")
        stub = Stub(c)
        lg = stub.logic()

        def _beat(i, ctx, e, ad, _s=stub):
            _s.trace.append("_beat")
        lg.actions["_beat"] = _beat
        from xstate_statemachine import create_machine
        m = create_machine(copy.deepcopy(c), logic=lg, strict_config=True)
        i = Interpreter(m, clock=None, max_queue_size=512,
                        overflow_policy=OverflowPolicy.RAISE)
        await i.start()
        await asyncio.sleep(0.05)
        await i.send("POLL_START")
        peak = 0
        for _ in range(140):
            await asyncio.sleep(0.02)
            peak = max(peak, nhandles(i))
            if stub.trace.count("_beat") >= 200:
                break
        beats = stub.trace.count("_beat")
        rec("/218/%s %d-beat raise(delay=) heartbeat holds <=1 handle" % (b, beats),
            peak <= 1 and beats >= 200,
            json.dumps({"peak_handles": peak, "beats": beats,
                        "last_error": repr(i.last_error)[:60],
                        "chain_trips": i.chain_trips}))
        await i.stop()


def nhandles(i):
    for a in ("_timer_handles", "_scheduled_handles", "_delayed_handles"):
        v = getattr(i, a, None)
        if v is None:
            continue
        if isinstance(v, dict):
            return sum(len(x) if isinstance(x, (list, set)) else 1
                       for x in v.values())
        return len(v)
    return -1


async def t219():
    """An action awaiting send(wait=True) on its own interpreter raises."""
    c = cfg("B10")
    box = {}

    async def bad(interp, ctx, evt, ad):
        try:
            await interp.send("ACK", wait=True)
            box["r"] = "NO-RAISE (hang averted?)"
        except Exception as e:
            box["r"] = type(e).__name__

    stub = Stub(c)
    lg = stub.logic()
    lg.actions["persist_fired_row"] = bad          # a true `async def` action
    from xstate_statemachine import create_machine
    m = create_machine(copy.deepcopy(c), logic=lg, strict_config=True)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    try:
        await asyncio.wait_for(i.send("CONDITION_MET"), 8)
    except asyncio.TimeoutError:
        box["r"] = "DEADLOCK(timeout)"
    await asyncio.sleep(0.05)
    rec("/219/B10 action awaiting own send(wait=True) -> ReentrantWaitError",
        box.get("r") == "ReentrantWaitError", json.dumps(box))
    await i.stop()
    # audit: any catalogue action that WOULD do this?
    hits = []
    for b in ("B6", "B7", "B8", "B9", "B10"):
        j = json.dumps(cfg(b))
        for k in ('"wait"', '"sendTo"'):
            if k in j:
                hits.append(b + k)
    rec("/219/catalogue audit: no action awaits its own send(wait=True)",
        not hits, json.dumps(hits) + " | stubs are pure; no contract action "
        "is specified as awaiting a receipt")


async def t221():
    """restore -> re-persist WITHOUT start() keeps the armed pacer."""
    c = copy.deepcopy(cfg("B6"))
    s = c["states"]["armed"]
    e = list(s.get("entry") or [])
    s["entry"] = e + [{"type": "raise", "params": {
        "event": "SLICE_DUE", "delay": 5000, "id": "pacer"}}]
    stub = Stub(c)
    m = build(c, stub)
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    await asyncio.sleep(0.05)
    await i.clock.increment(1000)
    await asyncio.sleep(0.05)
    blob = i.get_persisted_snapshot()
    if isinstance(blob, dict):
        blob = json.dumps(blob)
    await i.stop()
    j = Interpreter.from_snapshot(blob, build(c, Stub(c)),
                                  clock=SimulatedClock(), minimum_version=3)
    blob2 = j.get_persisted_snapshot()          # NO start()
    if isinstance(blob2, dict):
        blob2 = json.dumps(blob2)
    a = json.loads(blob)["scheduled_sends"]
    bb = json.loads(blob2)["scheduled_sends"]
    rec("/221/B6 re-persist without start() keeps the armed pacer",
        len(bb) == len(a) == 1 and bb == a,
        json.dumps({"orig": a, "repersisted": bb}))


async def t222():
    """A chain trip is sticky: chain_trips + last_chain_error latch."""
    c = copy.deepcopy(cfg("B10"))
    c["maxIterations"] = 4
    st = c["states"]["armed"]
    st.setdefault("on", {})["SPIN"] = {"actions": [
        {"type": "raise", "params": {"event": "SPIN"}}]}
    stub = Stub(c)
    m = build(c, stub)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=256,
                    overflow_policy=OverflowPolicy.RAISE)
    p = H.CvHooks()
    i.use(p)
    await i.start()
    await i.send("SPIN")
    await asyncio.sleep(0.2)
    trips1, latch1 = i.chain_trips, repr(i.last_chain_error)[:60]
    await i.send("DISABLE")           # one benign handled event
    await asyncio.sleep(0.1)
    rec("/222/B10 chain trip is sticky across a benign event",
        i.chain_trips == trips1 >= 1 and i.last_chain_error is not None,
        json.dumps({"trips": i.chain_trips, "latch": repr(i.last_chain_error)[:60],
                    "last_error_now": repr(i.last_error)[:60],
                    "hook_fired": len(p.chain_budget)}))
    rec("/222/B10 on_chain_budget_exceeded fired once per trip",
        len(p.chain_budget) == i.chain_trips,
        json.dumps({"hook": p.chain_budget, "trips": i.chain_trips}))
    i.clear_chain_error()
    rec("/222/B10 clear_chain_error() clears the latch, count stays",
        i.last_chain_error is None and i.chain_trips == trips1,
        json.dumps({"latch": repr(i.last_chain_error), "trips": i.chain_trips}))
    await i.stop()


async def main():
    for fn in (t218, t219, t221, t222):
        try:
            await fn()
        except Exception as e:
            import traceback; traceback.print_exc()
            rec("/" + fn.__name__ + "/CRASH", False, repr(e)[:200])
    H.dump("e6_round11.json")

asyncio.run(main())
