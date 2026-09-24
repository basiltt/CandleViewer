# -*- coding: utf-8 -*-
"""B12 ReplaySession: happy path + INV-B12-a..e."""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock

def _setc(i, c, e, a):
    d = getattr(e, "data", None) or {}
    if isinstance(d, dict) and "cursor" in d: c["cursor"] = d["cursor"]
def _reset(i, c, e, a): c["cursor"] = c["range_start"]
def _speed(i, c, e, a): c["speed"] = e.payload.get("speed", c["speed"])
def _slow(i, c, e, a): c["speed"] = c["speed"] / 2.0
def _cov(i, c, e, a):
    d = getattr(e, "data", None) or {}
    if isinstance(d, dict) and d.get("gaps"): c["coverage_gaps"] = list(d["gaps"])
IMPL = {"set_cursor": _setc, "reset_cursor_to_start": _reset, "set_speed": _speed,
        "slow_clock": _slow, "record_coverage": _cov}

def mk(loop=False, svc=None, cursor=0, gaps=None):
    cfg = H.load("B12")
    cfg["context"]["loop"] = loop
    cfg["context"]["range_start"] = 100
    s = dict(svc or {})
    s.setdefault("seek_and_prime", {"cursor": cursor or 100, "gaps": gaps or []})
    s.setdefault("emit_one_step", {"cursor": 999})
    st = H.Stub(cfg, guard_vals={"loop_enabled": loop}, svc=s, act_impl=IMPL)
    tp = H.TraceP()
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock()); it.use(tp)
    return it, st, tp


@scenario("B12-happy", "happy", "created->buffering->paused->playing->PAUSE->STEP->finished")
async def happy():
    it, st, tp = mk()
    await it.start()
    seq = [ids(it)]
    for ev in ("PREPARE",):
        await it.send(ev, wait=True); await quiesce(it); seq.append(ids(it))
    await it.send("PLAY", wait=True); await quiesce(it); seq.append(ids(it))
    await it.send("PAUSE", wait=True); await quiesce(it); seq.append(ids(it))
    await it.send("STEP", wait=True); await quiesce(it); seq.append(ids(it))
    await it.send("PLAY", wait=True); await quiesce(it)
    await it.send("RANGE_END", wait=True); await quiesce(it); seq.append(ids(it))
    await it.send("DESTROY", wait=True); await quiesce(it); seq.append(ids(it))
    await it.stop()
    exp = [["replay.created"], ["replay.paused"], ["replay.playing"], ["replay.paused"],
           ["replay.paused"], ["replay.finished"], ["replay.destroyed"]]
    return {"ok": seq == exp, "seq": seq, "expected": exp, "svc": st.svc_calls}


@scenario("B12-b-1", "INV-B12-b", "cursor monotonic during playback; SEEK is the only rewind")
async def cursor_mono():
    it, st, tp = mk(cursor=500)
    await it.start()
    await it.send("PREPARE", wait=True); await quiesce(it)
    c0 = it.context["cursor"]
    await it.send("STEP", wait=True); await quiesce(it)
    c1 = it.context["cursor"]
    # SEEK rewinds via buffering
    st.svc["seek_and_prime"] = {"cursor": 200, "gaps": []}
    await it.send("SEEK", to=200, wait=True); await quiesce(it)
    c2 = it.context["cursor"]
    await it.stop()
    return {"ok": c0 == 500 and c1 == 999 and c1 >= c0 and c2 == 200 and ids(it) == ["replay.paused"],
            "cursors": [c0, c1, c2], "final": ids(it)}


@scenario("B12-c", "INV-B12-c", "CONSUMER_SLOW slows clock, drops nothing, stays playing")
async def consumer_slow():
    it, st, tp = mk()
    await it.start()
    await it.send("PREPARE", wait=True); await quiesce(it)
    await it.send("PLAY", wait=True); await quiesce(it)
    for _ in range(3):
        await it.send("CONSUMER_SLOW", wait=True)
    await quiesce(it)
    sp, dropped = it.context["speed"], list(tp.dropped)
    ok = sp == 0.125 and not dropped and ids(it) == ["replay.playing"]
    await it.stop()
    return {"ok": ok, "speed": sp, "dropped": dropped, "states": ids(it),
            "slow_calls": st.trace.count("slow_clock")}


@scenario("B12-d", "INV-B12-d", "coverage_gaps surfaced explicitly from seek_and_prime")
async def coverage():
    gaps = [[100, 150], [300, 320]]
    it, st, tp = mk(gaps=gaps)
    await it.start()
    await it.send("PREPARE", wait=True); await quiesce(it)
    cg = it.context["coverage_gaps"]
    await it.stop()
    return {"ok": cg == gaps, "coverage_gaps": cg, "expected": gaps}


@scenario("B12-loop", "INV-B12-a", "RANGE_END with loop_enabled re-buffers and resets cursor")
async def looping():
    it, st, tp = mk(loop=True, cursor=700)
    await it.start()
    await it.send("PREPARE", wait=True); await quiesce(it)
    await it.send("PLAY", wait=True); await quiesce(it)
    n_seek = st.svc_calls.count("seek_and_prime")
    await it.send("RANGE_END", wait=True); await quiesce(it)
    end, n_seek2 = ids(it), st.svc_calls.count("seek_and_prime")
    await it.stop()
    return {"ok": end == ["replay.paused"] and n_seek2 == n_seek + 1
                  and "reset_cursor_to_start" in st.trace,
            "final": end, "seek_calls": (n_seek, n_seek2),
            "reset_called": "reset_cursor_to_start" in st.trace}


@scenario("B12-e", "INV-B12-e", "destroyed is final; further events rejected, not applied")
async def destroyed():
    it, st, tp = mk()
    await it.start()
    await it.send("PREPARE", wait=True); await quiesce(it)
    await it.send("DESTROY", wait=True); await quiesce(it)
    fin = ids(it)
    post = {}
    try:
        await it.send("PLAY", wait=True); await quiesce(it)
        post["PLAY"] = "accepted, states=%s" % ids(it)
    except Exception as e:
        post["PLAY"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    running = it.is_running
    await it.stop()
    return {"ok": fin == ["replay.destroyed"] and ids(it) == ["replay.destroyed"],
            "final": fin, "after_PLAY": post, "still_running": running,
            "deferred": it.deferred_count}


@scenario("B12-cancel", "INV-B12-a", "CANCEL during buffering -> paused; invoke result must not land later")
async def cancel_buffer():
    cfg = H.load("B12")
    async def slow_seek(i, c, e):
        await asyncio.sleep(0.5)
        return {"cursor": 4242, "gaps": []}
    st = H.Stub(cfg, guard_vals={"loop_enabled": False},
                svc={"seek_and_prime": slow_seek, "emit_one_step": {"cursor": 1}},
                act_impl=IMPL)
    tp = H.TraceP()
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock()); it.use(tp)
    await it.start()
    await it.send("PREPARE", wait=True); await asyncio.sleep(0.05)
    buffering = ids(it)
    await it.send("CANCEL", wait=True); await quiesce(it)
    right_after = ids(it)
    cur_after = it.context["cursor"]
    await asyncio.sleep(0.8)                       # let the abandoned service finish
    late = ids(it); cur_late = it.context["cursor"]
    await it.stop()
    return {"ok": buffering == ["replay.buffering"] and right_after == ["replay.paused"]
                  and late == ["replay.paused"] and cur_late == 0,
            "buffering": buffering, "after_cancel": right_after,
            "after_service_would_have_finished": late,
            "cursor": (cur_after, cur_late),
            "note": "cursor 4242 here would mean a cancelled seek still mutated state"}

if __name__ == "__main__":
    sys.exit(run_all("b12"))
