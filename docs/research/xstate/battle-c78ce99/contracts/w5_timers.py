# -*- coding: utf-8 -*-
"""STANDALONE: timers, #212 delayed self-sends and v3 armed-send snapshots
on the B1/B5 shapes, on c78ce99.

The catalogue JSON declares NO `after` and NO `raise(delay=)`: every
deadline (`arm_sl_deadline`, `arm_recon_deadline`, `arm_quiesce_deadline`,
`next_refill_at_us`) is a host-side timer an action stamps. This script
therefore GRAFTS the timers the wrapper would own onto the real contract
shapes and exercises them under the new #212 rule + #213 layout v3.
"""
from __future__ import annotations
import asyncio, copy, json, os, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cv78 as K  # noqa: E402
from xstate_statemachine import Interpreter, OverflowPolicy  # noqa: E402
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

os.chdir("<home>")


def graft_after(cfg, dotted, delay, target, actions=None):
    """Attach `after: {delay: ...}` to a state reached by dotted path."""
    n = cfg
    for part in dotted.split("."):
        n = n["states"][part]
    n.setdefault("after", {})[str(delay)] = {
        "target": target, "actions": actions or []}
    return cfg


def graft_raise_delay(cfg, dotted, delay, event, actions_key="entry",
                      send_id=None):
    """Attach a `raise(delay=)` self-send to a state's entry (#212)."""
    n = cfg
    for part in dotted.split("."):
        n = n["states"][part]
    lst = n.setdefault(actions_key, [])
    if isinstance(lst, str):
        lst = n[actions_key] = [lst]
    params = {"event": event, "delay": delay}
    if send_id:
        params["id"] = send_id
    lst.append({"type": "raise", "params": params})
    return cfg


async def t_b1_sl_deadline():
    """B1: the SL deadline `arm_sl_deadline` stamps, realised as `after`."""
    c = copy.deepcopy(K.cfg("B1"))
    graft_after(c, "protection.sl_pending", 2000,
                "#order.protection.sl_missing")
    st = K.Stub(c, guard_vals={"passes_all_gates": True, "ret_code_ok": True,
                               "exec_new_and_partial": True},
                svc={"attach_native_sl": lambda *a: asyncio.sleep(999)})
    m, i, p = await K.new_async(c, st)
    await K.send(i, "VALIDATE"); await K.send(i, "SEND")
    await K.send(i, "FIRST_FILL"); await K.quiesce(i, 3)
    pre = K.ids(i)
    K.rec("T.B1.sl.armed_waiting", "order.protection.sl_pending" in pre,
          str(pre))
    # v3 snapshot while an `after` deadline is armed
    blob = i.get_persisted_snapshot()
    raw = json.loads(blob if isinstance(blob, str) else json.dumps(blob))
    K.rec("T.B1.sl.snapshot_v3", raw.get("version") == 3, str(raw.get("version")))
    await i.clock.increment(2100); await K.quiesce(i, 3)
    post = K.ids(i)
    K.rec("T.B1.sl.deadline_fires", "order.protection.sl_missing" in post,
          str(post))
    K.rec("T.B1.sl.naked_alert", "raise_naked_position_alert" in p.actions, "")
    await i.stop()


async def t_raise_delay_heartbeat():
    """#212: a self-paced `raise(delay=1)` cycle is a periodic process, not
    a runaway.

    Grafted onto B5's real refill cycle -- `working` --CHILD_CANCELLED-->
    `waiting_refill` --REFILL_DUE--> `submitting_slice` --onDone-->
    `working` -- each hop armed by a 1 ms delayed self-raise. Under the
    #206 rule this died at `maxIterations` beats; under #212 it must run
    indefinitely, exactly as an `after: 1` cycle always has.
    """
    c = copy.deepcopy(K.cfg("B5"))
    graft_raise_delay(c, "working", 1, "CHILD_CANCELLED")
    graft_raise_delay(c, "waiting_refill", 1, "REFILL_DUE")
    st = K.Stub(c, guard_vals={"preflight_invalid": False,
                               "remaining_is_zero": False,
                               "slices_exhausted": False,
                               "is_post_only_reject": False,
                               "failures_exhausted": False})
    m = K.build(c, st)
    i = Interpreter(m, clock=SimulatedClock(), max_queue_size=256,
                    overflow_policy=OverflowPolicy.RAISE)
    p = K.CvHooks(); i.use(p)
    await i.start(); await K.quiesce(i, 3)
    K.rec("T.212.cycle_started", "iceberg.working" in K.ids(i), str(K.ids(i)))
    beats = 0
    for _ in range(40):          # 40 ticks >> any maxIterations default
        await i.clock.increment(1)
        await K.quiesce(i, 2)
        if i.status != "running":
            break
        beats += 1
    laps = st.svc_calls.count("submit_child")
    K.rec("T.212.heartbeat_survives_40_beats",
          i.status == "running" and i.error is None and beats == 40,
          "beats=%d laps=%d status=%s err=%r states=%s"
          % (beats, laps, i.status, i.error, K.ids(i)))
    K.rec("T.212.cycle_actually_lapped", laps >= 5,
          "submit_child x%d" % laps)
    K.rec("T.212.no_runaway_error",
          not any("Runaway" in e for e in p.errors), str(p.errors[:2]))
    await i.stop()


async def t_armed_send_snapshot():
    """#213: an armed, unfired delayed self-send survives snapshot/restore.

    B3's `submitting` arms a submit timeout; realised as a
    `raise(delay=)` whose firing is the ONLY exit from the state.
    """
    c = copy.deepcopy(K.cfg("B3"))
    # `arm_submit_timeout` is already a contract action and `submitting`
    # already handles SUBMIT_TIMEOUT -> `#leg.resolving`; realise the arm
    # as the raise(delay=) the wrapper would issue.
    graft_raise_delay(c, "submitting", 5000, "SUBMIT_TIMEOUT",
                      send_id="submit_timeout")
    st = K.Stub(c, guard_vals={"should_skip": False, "passes_preflight": True})
    m, i, p = await K.new_async(c, st)
    await K.quiesce(i, 3)
    K.rec("T.213.parked_in_submitting", "leg.submitting" in K.ids(i),
          str(K.ids(i)))
    await i.clock.increment(1000)          # partially elapse
    await K.quiesce(i, 2)
    blob = i.get_persisted_snapshot()
    raw = json.loads(blob if isinstance(blob, str) else json.dumps(blob))
    sched = raw.get("scheduled_sends") or []
    K.rec("T.213.scheduled_sends_present", len(sched) == 1, json.dumps(sched)[:300])
    rem = (sched[0].get("remaining_ms") if sched else None)
    K.rec("T.213.remaining_delay_recorded",
          rem is not None and 3500 < float(rem) <= 4000, str(rem))
    K.rec("T.213.has_send_id",
          bool(sched) and sched[0].get("send_id") == "submit_timeout",
          str(sched[0].get("send_id") if sched else None))
    await i.stop()
    # restore and prove the timer still fires with its REMAINING delay
    st2 = K.Stub(c, guard_vals={"should_skip": False, "passes_preflight": True})
    m2 = K.build(c, st2)
    j = Interpreter.from_snapshot(
        blob if isinstance(blob, str) else json.dumps(blob), m2,
        clock=SimulatedClock(), minimum_version=3)
    await j.start(); await K.quiesce(j, 3)
    K.rec("T.213.restored_state", "leg.submitting" in K.ids(j), str(K.ids(j)))
    await j.clock.increment(3000); await K.quiesce(j, 2)
    mid = K.ids(j)
    K.rec("T.213.not_early", "leg.submitting" in mid, str(mid))
    await j.clock.increment(1200); await K.quiesce(j, 3)
    # SUBMIT_TIMEOUT -> `resolving` -> `lookup_by_link_id` resolves; with
    # both lookup guards false the contract's default arm is `leg.rejected`.
    K.rec("T.213.rearmed_and_fires",
          "leg.submitting" not in K.ids(j)
          and "lookup_by_link_id" in st2.svc_calls,
          "states=%s svc=%s" % (K.ids(j), st2.svc_calls))
    await j.stop()


async def main():
    await t_b1_sl_deadline()
    await t_raise_delay_heartbeat()
    await t_armed_send_snapshot()
    K.dump("res_timers.json")


if __name__ == "__main__":
    asyncio.run(main())
