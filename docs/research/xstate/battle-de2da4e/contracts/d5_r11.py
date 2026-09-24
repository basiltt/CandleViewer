# -*- coding: utf-8 -*-
"""d5: round-11 axis (#218 #219 #221 #222) on the B16-B20 control charts.
Run: d5_r11.py [async|def]
"""
from __future__ import annotations
import asyncio, json, os, sys
os.environ["CV_SVC_STYLE"] = sys.argv[1] if len(sys.argv) > 1 else "async"
STYLE = os.environ["CV_SVC_STYLE"]
import cvde as H
from cvde import Stub
from xstate_statemachine import Interpreter, SyncInterpreter, OverflowPolicy
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import ReentrantWaitError
rec = H.rec

def S(c, **kw):
    kw.setdefault("svc_style", STYLE); return Stub(c, **kw)

def J(c):
    return json.loads(json.dumps(c))

GV18 = {"cancel_working_requested": True, "flatten_requested": True,
        "all_accounts_flat": True, "owner_and_elevated": True,
        "owner_and_elevated_and_acknowledged_residual": True}


# --------------------------------------------- #218 heartbeat handle leak ---
async def a218():
    """B20 with the poller we would actually ship: a raise(delay=) heartbeat
    on `locked` (CV-C50). 200 beats must not accumulate clock handles."""
    c = J(H.cfg("B20"))
    lk = c["states"]["locked"]
    lk.setdefault("entry", [])
    if isinstance(lk["entry"], str):
        lk["entry"] = [lk["entry"]]
    lk["entry"] = list(lk["entry"]) + [
        {"type": "xstate.raise",
         "params": {"event": "HEARTBEAT", "delay": 1, "id": "beat"}}]
    lk.setdefault("on", {})["HEARTBEAT"] = {
        "target": "#risk_lockout.locked", "reenter": True}
    c["maxIterations"] = 5
    st = S(c, guard_vals={"until_mode_is_time_based": True,
                          "breaches_daily_loss_cap": True,
                          "owner_and_elevated_and_override_permitted": True})
    m = H.build(c, st)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                    overflow_policy=OverflowPolicy.RAISE)
    p = H.CvHooks(); i.use(p)
    await i.start(); await H.quiesce(i, 3)
    await H.send(i, "MANUAL_LOCK"); await H.quiesce(i, 3)
    peak = 0
    for _ in range(200):
        await i.clock.increment(1)
        await H.quiesce(i, 1)
        n = sum(len(v) for v in i._timer_handles.values())
        peak = max(peak, n)
    hb = sum(1 for t in p.transitions if t.startswith("HEARTBEAT"))
    rec("218/heartbeat handles bounded", peak <= 1,
        json.dumps({"peak_handles": peak, "beats": hb, "status": i.status,
                    "error": repr(i.error)[:120],
                    "chain_trips": i.chain_trips}))
    rec("218/heartbeat survives 200 beats (#212 live)",
        i.status == "running" and i.error is None and hb >= 100,
        json.dumps({"beats": hb, "status": i.status}))
    rec("218/heartbeat does not trip the chain budget", i.chain_trips == 0,
        "chain_trips=%d last=%r" % (i.chain_trips, i.last_chain_error))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass


# ------------------------- #219 an action awaiting its own send(wait=True) --
async def a219():
    """Our catalogue's broadcast_* / page_owner wrappers are the realistic
    place to write `await interp.send(..., wait=True)`. Confirm the new
    refusal and confirm the documented escape hatch still works.

    The action MUST be a real `async def` in MachineLogic -- returning a
    coroutine from a sync action is not awaited by the engine."""
    c = J(H.cfg("B18"))

    async def run(impl, seen):
        st = S(c, guard_vals=dict(GV18))
        logic = st.logic()

        async def broadcast_kill_switch(interp, ctx, evt, ad):
            st.trace.append("broadcast_kill_switch")
            await impl(interp, seen)
        logic.actions["broadcast_kill_switch"] = broadcast_kill_switch
        from xstate_statemachine import create_machine
        import copy as _c
        m = create_machine(_c.deepcopy(c), logic=logic, strict_config=True,
                           strict_targets=True)
        i = Interpreter(m, clock=SimulatedClock(), max_queue_size=64,
                        overflow_policy=OverflowPolicy.RAISE)
        pl = H.CvHooks(); i.use(pl)
        await i.start(); await H.quiesce(i, 3)
        r = await H.send(i, "ENGAGE", timeout=8)
        await H.quiesce(i, 4)
        state, status = H.ids(i), i.status
        try:
            await asyncio.wait_for(i.stop(), 5)
        except Exception:
            pass
        return r, state, status, i

    # (a) the refused shape
    seen = {}

    async def bad(interp, seen):
        try:
            await interp.send("RELEASE", wait=True)
            seen["r"] = "returned"
        except ReentrantWaitError:
            seen["r"] = "ReentrantWaitError"
        except Exception as e:
            seen["r"] = repr(e)[:140]

    r, state, status, i = await run(bad, seen)
    rec("219/self send(wait=True) inside an action raises, no hang",
        seen.get("r") == "ReentrantWaitError" and not r.get("timeout"),
        json.dumps({"seen": seen, "sec": round(r.get("sec", -1), 3),
                    "status": status, "states": state}))

    # (b) the documented escape hatch
    later = {}

    async def ok(interp, seen):
        later["fut"] = asyncio.ensure_future(interp.send("RELEASE", wait=True))

    r2, state2, status2, i2 = await run(ok, {})
    try:
        await asyncio.wait_for(later["fut"], 5)
        hatch = "resolved"
    except Exception as e:
        hatch = repr(e)[:140]
    rec("219/deferred receipt (ensure_future) still works", hatch == "resolved",
        json.dumps({"hatch": hatch, "states": state2, "status": status2}))


def a219_sync():
    """Parity: the sync engine refuses the same shape (wait=True from
    inside an action)."""
    c = J(H.cfg("B18"))
    seen = {}

    def bad(interp, ctx, evt, ad):
        seen["ran"] = True
        try:
            interp.send("RELEASE", wait=True)
            seen["r"] = "returned"
        except ReentrantWaitError:
            seen["r"] = "ReentrantWaitError"
        except Exception as e:
            seen["r"] = repr(e)[:140]
        # fire-and-forget is still allowed
        try:
            interp.send("RELEASE")
            seen["ff"] = "accepted"
        except Exception as e:
            seen["ff"] = repr(e)[:80]

    st = Stub(c, guard_vals=dict(GV18), sync=True,
              act_impl={"broadcast_kill_switch": bad})
    m, i, p = H.new_sync(c, st)
    try:
        i.send("ENGAGE")
    except Exception as e:
        seen["outer"] = repr(e)[:140]
    rec("219/sync engine refuses the same shape (wait=True)",
        seen.get("r") == "ReentrantWaitError", json.dumps(seen))
    try:
        i.stop()
    except Exception:
        pass


# ---------------- #221 restore -> re-persist without start() keeps deadlines --
async def a221():
    """The journal-compaction shape: load a B20 blob carrying an armed expiry
    deadline, re-persist it WITHOUT start(), and check the deadline survives."""
    c = J(H.cfg("B20"))
    lk = c["states"]["locked"]
    lk.setdefault("entry", [])
    if isinstance(lk["entry"], str):
        lk["entry"] = [lk["entry"]]
    lk["entry"] = list(lk["entry"]) + [
        {"type": "xstate.raise",
         "params": {"event": "EXPIRY_DUE", "delay": 4000, "id": "expiry"}}]
    gv = {"until_mode_is_time_based": True,
          "breaches_daily_loss_cap": True,
          "owner_and_elevated_and_override_permitted": True}
    st = S(c, guard_vals=dict(gv))
    m, i, p = await H.new_async(c, st)
    await H.send(i, "MANUAL_LOCK"); await H.quiesce(i, 3)
    await i.clock.increment(1000); await H.quiesce(i, 2)
    blob1 = i.get_persisted_snapshot()
    if isinstance(blob1, dict):
        blob1 = json.dumps(blob1)
    n1 = len(json.loads(blob1)["scheduled_sends"])
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass

    # compaction job: from_snapshot, re-persist, never start
    st2 = S(c, guard_vals=dict(gv)); m2 = H.build(c, st2)
    j = Interpreter.from_snapshot(blob1, m2, clock=SimulatedClock(),
                                  minimum_version=3)
    blob2 = j.get_persisted_snapshot()
    if isinstance(blob2, dict):
        blob2 = json.dumps(blob2)
    pay2 = json.loads(blob2)
    n2 = len(pay2["scheduled_sends"])
    rec("221/re-persist without start() keeps scheduled_sends",
        n1 == 1 and n2 == 1,
        json.dumps({"n_before": n1, "n_after": n2, "records": pay2["scheduled_sends"]}))

    # and the twice-written blob still fires on the remainder
    st3 = S(c, guard_vals=dict(gv)); m3 = H.build(c, st3)
    k = Interpreter.from_snapshot(blob2, m3, clock=SimulatedClock(),
                                  minimum_version=3)
    await k.start(); await H.quiesce(k, 3)
    await k.clock.increment(2999); await H.quiesce(k, 2)
    mid = H.ids(k)
    await k.clock.increment(2); await H.quiesce(k, 3)
    end = H.ids(k)
    rec("221/compacted blob fires on the REMAINDER (3000ms), not from zero",
        mid == ["risk_lockout.locked"] and end == ["risk_lockout.clear"],
        json.dumps({"at_2999": mid, "at_3001": end}))
    try:
        await asyncio.wait_for(k.stop(), 5)
    except Exception:
        pass


# --------------------------------------- #222 a chain-budget trip is sticky --
async def a222():
    """B18's mandated rollback+onDone runaway, then one benign event. Under
    the old rule `last_error` was erased; the latch must survive."""
    c = J(H.cfg("B18")); c["maxIterations"] = 5
    gv = dict(GV18, all_accounts_flat=False)
    st = S(c, guard_vals=gv, raising=("page_owner",))
    m, i, p = await H.new_async(c, st)
    await H.send(i, "ENGAGE"); await H.quiesce(i, 8)
    trips = i.chain_trips
    latch = repr(i.last_chain_error)[:100]
    hook = list(p.chain_budget)
    # one benign, handled event
    await H.send(i, "RELEASE"); await H.quiesce(i, 6)
    rec("222/chain trip is latched and counted",
        trips >= 1 and i.last_chain_error is not None,
        json.dumps({"trips": trips, "latch": latch, "hook": hook[:2],
                    "states": H.ids(i)}))
    rec("222/benign event does not erase the latch",
        i.last_chain_error is not None and i.chain_trips >= trips,
        json.dumps({"trips_after": i.chain_trips,
                    "latch_after": repr(i.last_chain_error)[:100],
                    "last_error": repr(i.error)[:100]}))
    rec("222/hook fires once per trip", len(hook) == trips,
        json.dumps({"hook_n": len(hook), "trips": trips}))
    i.clear_chain_error()
    rec("222/clear_chain_error clears the latch, keeps the count",
        i.last_chain_error is None and i.chain_trips == i.chain_trips >= 1,
        json.dumps({"latch": repr(i.last_chain_error), "trips": i.chain_trips}))
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:
        pass


# ------------------------------- chain_trips == 0 on every happy path -------
async def a_happy_clean():
    paths = {
        "B16": (["MFA_OK", "REQUEST", "STEP_UP_OK"], {}),
        "B17": (["EVIDENCE_RECORDED", "ENABLE_REQUESTED", "DISABLE_REQUESTED"],
                {"all_evidence_present": True,
                 "owner_and_elevated_and_evidence_still_valid": True,
                 "owner_and_elevated": True}),
        "B18": (["ENGAGE", "RELEASE"], dict(GV18)),
        "B19": (["SWEEP_DUE"],
                {"divergences_found_and_auto_remediate": False,
                 "unresolved_divergences": False,
                 "failures_exhausted": False}),
        "B20": (["MANUAL_LOCK", "EXPIRY_DUE"],
                {"until_mode_is_time_based": True,
                 "breaches_daily_loss_cap": True,
                 "owner_and_elevated_and_override_permitted": True}),
    }
    bad = {}
    for b, (script, gv) in paths.items():
        c = H.cfg(b)
        st = S(c, guard_vals=dict(gv))
        m, i, p = await H.new_async(c, st)
        for step in script:
            name, pl = (step, {}) if isinstance(step, str) else step
            await H.send(i, name, **pl)
            await H.quiesce(i, 3)
        bad[b] = {"trips": i.chain_trips, "states": H.ids(i),
                  "latch": repr(i.last_chain_error)[:60]}
        try:
            await asyncio.wait_for(i.stop(), 5)
        except Exception:
            pass
    rec("222/chain_trips == 0 on every happy path",
        all(v["trips"] == 0 for v in bad.values()), json.dumps(bad))


async def main():
    await a218()
    await a219()
    a219_sync()
    await a221()
    await a222()
    await a_happy_clean()
    H.dump("d5_r11.json")

asyncio.run(main())
