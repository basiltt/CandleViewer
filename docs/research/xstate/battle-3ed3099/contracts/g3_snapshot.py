# -*- coding: utf-8 -*-
"""Step 3: snapshot at quiescence between EVERY macrostep, restore, resume,
and compare the resulting trace with an uninterrupted run.

Must never raise SnapshotMidStepError (the machine is quiesced at every
snapshot point, which is precisely the window #102 declared legal).
"""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_harness as H
from g3_harness import scenario, run_all, ids, quiesce
from xstate_statemachine import (Interpreter, SnapshotMidStepError,
                                 SnapshotCorruptError)
from xstate_statemachine.clock import SimulatedClock

import g3_b11, g3_b13, g3_b14_b15, g3_b12
H._REG.clear()   # importing the per-machine modules registers their scenarios


# ---------------------------------------------------------------- scripts --
SCRIPTS = {
    "B11": (lambda: H.Stub(H.load("B11"), guard_vals=g3_b11.GV, act_impl=g3_b11.IMPL),
            [("REASON_ADDED", {"reason": "chart"}),
             ("GAP_DETECTED", {"seq": 1}),
             ("STREAM_UNHEALTHY", {"s": "trade"}),
             ("STREAM_HEALTHY", {"s": "trade"}),
             ("REASON_REMOVED", {"reason": "chart"}),
             ("LINGER_DUE", {})]),
    "B12": (lambda: H.Stub(H.load("B12"), guard_vals={"loop_enabled": False},
                           svc={"seek_and_prime": {"cursor": 100, "gaps": []},
                                "emit_one_step": {"cursor": 101}},
                           act_impl=g3_b12.IMPL),
            [("PREPARE", {}), ("PLAY", {}), ("SET_SPEED", {"speed": 2.0}),
             ("PAUSE", {}), ("STEP", {}), ("PLAY", {}), ("RANGE_END", {})]),
    "B13": (lambda: H.Stub(H.load("B13"),
                           guard_vals={"is_private": False,
                                       "connection_budget_exhausted": False},
                           act_impl=g3_b13.IMPL),
            [("CONNECT", {}), ("PONG", {"us": 7}),
             ("TOPICS_CHANGED", {"topics": ["a", "b"]}),
             ("SOCKET_CLOSED", {}), ("BACKOFF_DUE", {}), ("SHUTDOWN", {})]),
    "B14": (lambda: H.Stub(H.load("B14"), act_impl=g3_b14_b15.B14_IMPL),
            [("SUBSCRIBE", {}), ("DELTA", {"seq": 5}), ("SNAPSHOT", {"seq": 4}),
             ("DELTA", {"seq": 6}), ("SEQUENCE_GAP", {"us": 9}),
             ("SNAPSHOT", {"seq": 10})]),
    "B15": (lambda: H.Stub(H.load("B15"),
                           guard_vals={"mark_crossed_liq_price": False,
                                       "below_maintenance_margin": True,
                                       "above_maintenance_margin": False},
                           act_impl=g3_b14_b15.B15_IMPL),
            [("MARK_UPDATE", {"px": 1}), ("MARK_UPDATE", {"px": 2})]),
}


def fingerprint(it, st):
    return {"states": ids(it),
            "context": json.loads(json.dumps(
                {k: v for k, v in it.context.items() if not k.startswith("_")},
                default=str, sort_keys=True)),
            "private": json.loads(json.dumps(
                {k: v for k, v in it.context.items() if k.startswith("_")},
                default=str, sort_keys=True)),
            "actions": list(st.trace)}


async def uninterrupted(b):
    mkstub, script = SCRIPTS[b]
    cfg = H.load(b)
    st = mkstub()
    it = Interpreter(H.build(cfg, st), clock=SimulatedClock())
    await it.start()
    await quiesce(it)
    marks = []
    for ev, p in script:
        await it.send(ev, wait=True, **p)
        await quiesce(it)
        marks.append(fingerprint(it, st))
    await it.stop()
    return marks


async def with_snapshot_each_step(b):
    """After every macrostep: snapshot at quiescence, restore, continue there."""
    mkstub, script = SCRIPTS[b]
    cfg = H.load(b)
    st = mkstub()
    machine = H.build(cfg, st)
    it = Interpreter(machine, clock=SimulatedClock())
    await it.start()
    await quiesce(it)
    marks, notes = [], []
    for idx, (ev, p) in enumerate(script):
        await it.send(ev, wait=True, **p)
        await quiesce(it)
        # --- quiescent? then snapshot must be legal ---
        q = {"queue_depth": it.queue_depth, "deferred": it.deferred_count}
        try:
            blob = it.get_persisted_snapshot()
        except SnapshotMidStepError as e:
            notes.append({"step": idx, "event": ev, "MIDSTEP": str(e)[:200], "quiesce": q})
            marks.append(fingerprint(it, st))
            continue
        pre = fingerprint(it, st)
        await it.stop()
        # --- restore into a fresh interpreter, carrying the action trace over ---
        it = Interpreter.from_snapshot(
            json.dumps(blob) if not isinstance(blob, str) else blob,
            machine, clock=SimulatedClock(), restart_timers=True)
        await it.start()
        await quiesce(it)
        post = fingerprint(it, st)
        if pre["states"] != post["states"] or pre["context"] != post["context"]:
            notes.append({"step": idx, "event": ev, "DRIFT": {"pre": pre, "post": post}})
        marks.append(post)
    await it.stop()
    return marks, notes


def compare(b, a, c):
    diffs = []
    for i, (x, y) in enumerate(zip(a, c)):
        if x["states"] != y["states"]:
            diffs.append({"step": i, "field": "states", "plain": x["states"], "snap": y["states"]})
        if x["context"] != y["context"]:
            diffs.append({"step": i, "field": "context", "plain": x["context"], "snap": y["context"]})
    if len(a) != len(c):
        diffs.append({"len": (len(a), len(c))})
    return diffs


def _mk(b):
    async def fn():
        plain = await uninterrupted(b)
        snapd, notes = await with_snapshot_each_step(b)
        diffs = compare(b, plain, snapd)
        midstep = [n for n in notes if "MIDSTEP" in n]
        return {"ok": not diffs and not midstep,
                "steps": len(plain),
                "midstep_errors": midstep,
                "trace_divergences": diffs[:6],
                "n_divergences": len(diffs),
                "restore_drift": [n for n in notes if "DRIFT" in n][:3],
                "final_plain": plain[-1]["states"] if plain else None,
                "final_snapshotted": snapd[-1]["states"] if snapd else None}
    fn.__name__ = "snap_" + b
    return fn


for _b in ("B11", "B12", "B13", "B14", "B15"):
    scenario("SNAP-" + _b, "snapshot", "snapshot+restore at every macrostep == uninterrupted run")(_mk(_b))


if __name__ == "__main__":
    sys.exit(run_all("snapshot"))
