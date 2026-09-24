# -*- coding: utf-8 -*-
"""STANDALONE: the three mandated hazard drives on the contract shapes.

D1  always --> a state that invokes a child (B14 `desynced` always->
    `snapshot_pending`; here the target also invokes). The roll-forward must
    cancel the armed invoke before submission (#193) and must not leak.

D2  B18-shaped send_priority under a self-generated chain: an external
    priority send must NEVER be shed as chain_budget (#192/#180), and a kill
    switch must preempt a busy inbox. 0 dropped.

D3  Engine-event provenance (#195): a hand-built DoneEvent must be refused
    under strict and must not drive a real onDone.

Exit 0 = all three hold. Exit 1 = any violation (details printed).
"""
from __future__ import annotations
import asyncio, json, os, sys

from xstate_statemachine import (Interpreter, MachineLogic, create_machine,
                                 OverflowPolicy)
from xstate_statemachine.clock import SimulatedClock

STYLE = os.environ.get("CV_SVC_STYLE", "async")
FAIL = []


def mksvc(fn):
    if STYLE == "def":
        def s(i, c, e):
            return fn(i, c, e)
    else:
        async def s(i, c, e):
            return fn(i, c, e)
    return s


# ------------------------------------------------------------------ D1 ----
D1 = {
    "id": "d1", "actionErrorPolicy": "rollback", "onUnhandled": "error",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "initial": "live", "context": {"resyncs": 0},
    "states": {
        "live": {"on": {"GAP": {"target": "#d1.desynced"}}},
        # transient: entry runs, then `always` immediately rolls forward
        "desynced": {"entry": ["bump"],
                     "invoke": {"id": "doomed", "src": "doomed_svc",
                                "onDone": {"target": "#d1.live"}},
                     "always": {"target": "#d1.snapshot_pending"}},
        "snapshot_pending": {"invoke": {"id": "snap", "src": "snap_svc",
                                        "onDone": {"target": "#d1.live"}}},
    },
}


async def d1():
    hits = {"doomed": 0, "snap": 0}

    def bump(i, c, e, a):
        c["resyncs"] = c.get("resyncs", 0) + 1

    logic = MachineLogic(
        actions={"bump": bump},
        services={"doomed_svc": mksvc(lambda i, c, e: hits.__setitem__("doomed", hits["doomed"] + 1) or {"ok": 1}),
                  "snap_svc": mksvc(lambda i, c, e: hits.__setitem__("snap", hits["snap"] + 1) or {"ok": 1})},
        strict=True)
    it = Interpreter(create_machine(json.loads(json.dumps(D1)), logic=logic,
                                    strict_targets=True), clock=SimulatedClock())
    await it.start()
    await it.send("GAP", wait=True)
    for _ in range(8):
        await asyncio.sleep(0.03)
    out = {"drive": "D1 always->invoked-child", "style": STYLE,
           "doomed_submitted": hits["doomed"], "snap_submitted": hits["snap"],
           "resyncs": it.context.get("resyncs"),
           "cfg": sorted(it.current_state_ids)}
    await asyncio.wait_for(it.stop(), 10)
    # #193: the rolled-FORWARD invoke must never be submitted
    out["ok"] = hits["doomed"] == 0 and hits["snap"] >= 1
    if not out["ok"]:
        FAIL.append("D1: rolled-forward invoke was submitted %d time(s)" % hits["doomed"])
    return out


# ------------------------------------------------------------------ D2 ----
D2 = {
    "id": "d2", "actionErrorPolicy": "rollback", "onUnhandled": "defer",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "initial": "active", "context": {"n": 0, "killed": False},
    "states": {
        "active": {"on": {
            "TICK": {"actions": ["chain"]},
            "WORK": {"actions": ["count"]},
            "KILL": {"target": "#d2.dead"},
        }},
        "dead": {"type": "final"},
    },
}


async def d2():
    seen = {"work": 0, "chain": 0}
    dropped = []

    def count(i, c, e, a):
        seen["work"] += 1
        c["n"] = c.get("n", 0) + 1

    def chain(i, c, e, a):
        # self-generated chain: keep raising until the budget cuts us off
        seen["chain"] += 1
        if seen["chain"] < 40:
            i.send("TICK")

    from xstate_statemachine.plugins import PluginBase

    class P(PluginBase):
        def on_event_dropped(self, interp, event, reason):
            dropped.append((getattr(event, "type", "?"), str(reason)))

    logic = MachineLogic(actions={"count": count, "chain": chain}, strict=True)
    it = Interpreter(create_machine(json.loads(json.dumps(D2)), logic=logic,
                                    strict_targets=True),
                     clock=SimulatedClock(), max_queue_size=64,
                     overflow_policy=OverflowPolicy.RAISE)
    it.use(P())
    await it.start()
    # start a self-generated chain, then fire external priority sends into it
    asyncio.ensure_future(it.send("TICK"))
    ext = 60
    for _ in range(ext):
        await it.send_priority("WORK")
    for _ in range(10):
        await asyncio.sleep(0.03)
    mid = {"work_applied": seen["work"], "dropped": list(dropped)}
    # kill switch must preempt
    await it.send_priority("KILL")
    for _ in range(6):
        await asyncio.sleep(0.03)
    out = {"drive": "D2 external priority under self-chain", "style": STYLE,
           "external_sent": ext, "work_applied": seen["work"],
           "dropped": dropped[:6], "n_dropped": len(dropped),
           "cfg_after_kill": sorted(it.current_state_ids),
           "mid": mid}
    try:
        await asyncio.wait_for(it.stop(), 10)
    except asyncio.TimeoutError:
        out["stop_hung"] = True
    shed = [d for d in dropped if "chain" in d[1].lower() or "budget" in d[1].lower()]
    out["externally_shed"] = shed[:5]
    out["ok"] = seen["work"] == ext and not shed and sorted(it.current_state_ids) == ["d2.dead"]
    if not out["ok"]:
        FAIL.append("D2: work_applied=%d/%d shed=%d cfg=%s"
                    % (seen["work"], ext, len(shed), sorted(it.current_state_ids)))
    return out


# ------------------------------------------------------------------ D3 ----
async def d3():
    from xstate_statemachine import events as EV
    hits = {"real": 0}
    cfg = {
        "id": "d3", "actionErrorPolicy": "rollback", "onUnhandled": "defer",
        "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
        "initial": "arm", "context": {},
        "states": {
            "arm": {"on": {"GO": {"target": "#d3.busy"}}},
            "busy": {"invoke": {"id": "fill", "src": "slow",
                                "onDone": {"target": "#d3.done_"}}},
            "done_": {"entry": ["mark"]},
        },
    }

    def mark(i, c, e, a):
        hits["real"] += 1

    import time as _t

    def body(i, c, e):
        (_t.sleep if STYLE == "def" else _t.sleep)(0.4)
        return {"ok": 1}

    if STYLE == "def":
        def slow(i, c, e):
            _t.sleep(0.4)
            return {"ok": 1}
    else:
        async def slow(i, c, e):
            await asyncio.sleep(0.4)
            return {"ok": 1}

    logic = MachineLogic(actions={"mark": mark}, services={"slow": slow},
                         strict=True)
    it = Interpreter(create_machine(json.loads(json.dumps(cfg)), logic=logic,
                                    strict_targets=True), clock=SimulatedClock())
    await it.start()
    asyncio.ensure_future(it.send("GO"))
    await asyncio.sleep(0.05)
    forged_refused, note = None, None
    try:
        DoneEvent = getattr(EV, "DoneEvent", None)
        if DoneEvent is None:
            note = "DoneEvent not exported"
        else:
            forged = DoneEvent("done.invoke.fill", {"forged": True}, "fill", None) \
                if len(getattr(DoneEvent, "_fields", ())) == 4 else DoneEvent("done.invoke.fill", {"forged": True}, "fill")
            await it.send(forged, wait=True)
            forged_refused = False
    except Exception as exc:
        forged_refused = "%s: %s" % (type(exc).__name__, str(exc)[:160])
    cfg_after_forge = sorted(it.current_state_ids)
    for _ in range(25):
        await asyncio.sleep(0.03)
    out = {"drive": "D3 forged DoneEvent provenance", "style": STYLE,
           "forged_refused": forged_refused, "note": note,
           "cfg_right_after_forge": cfg_after_forge,
           "cfg_after_real_service": sorted(it.current_state_ids),
           "real_onDone_entries": hits["real"]}
    await asyncio.wait_for(it.stop(), 10)
    out["ok"] = bool(forged_refused) and cfg_after_forge != ["d3.done_"] and hits["real"] == 1
    if not out["ok"]:
        FAIL.append("D3: forged=%r cfg_after_forge=%s real=%d"
                    % (forged_refused, cfg_after_forge, hits["real"]))
    return out


async def main():
    rows = []
    for fn in (d1, d2, d3):
        try:
            rows.append(await asyncio.wait_for(fn(), 60))
        except Exception as exc:
            rows.append({"drive": fn.__name__, "EXC": "%s: %s" % (type(exc).__name__, exc)})
            FAIL.append("%s raised %s" % (fn.__name__, type(exc).__name__))
    print(json.dumps(rows, indent=1, default=str))
    print("\nFAILURES:", json.dumps(FAIL, indent=1) if FAIL else "none")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
