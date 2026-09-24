"""N2 -- #117 from_snapshot(clock=) + #128 restart_timers / has_dormant_timers.

This is the direct re-test of D-determinism-5: can a replay harness checkpoint
mid-stream and resume with virtual time intact and get the same tail?

  R1  from_snapshot(clock=SimulatedClock()) -> restored.clock is that clock
  R2  has_dormant_timers is True after a static restore of a state with an
      `after`, and False once restart_timers=True + start() re-arms it
  R3  checkpoint-and-resume tail vs straight-through tail, SimulatedClock both
      sides, both engines
  R4  determinism of the resume: two resumes from the same snapshot bytes
      produce identical tails
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

from dmachine import Recorder, build, canon_snapshot, make_script  # noqa: E402
from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

SPLIT = 120
TOTAL = 300

TIMED = {
    "id": "tm",
    "initial": "idle",
    "context": {"late": 0},
    "states": {
        "idle": {"on": {"GO": "armed"}},
        "armed": {"after": {"50": {"target": "idle", "actions": ["late"]}}},
    },
}


def timed_machine():
    def late(i, c, e, a):
        c["late"] += 1

    return create_machine(TIMED, logic=MachineLogic(actions={"late": late}))


async def straight_async(script, split):
    rec = Recorder()
    clock = SimulatedClock()
    i = Interpreter(build(rec), clock=clock)
    await i.start()
    mid = None
    for k, step in enumerate(script):
        if step[0] == "tick":
            await clock.increment(step[1])
        else:
            await i.send(step[1], **step[2])
        if k == split:
            mid = i.get_persisted_snapshot()
            head = len(rec.actions)
    end = canon_snapshot(i.get_persisted_snapshot())
    await i.stop()
    return rec.actions, mid, end, head


async def resume_async(script, split, mid_json):
    rec = Recorder()
    clock = SimulatedClock()
    i = Interpreter.from_snapshot(mid_json, build(rec), clock=clock)
    await i.start()
    for step in script[split + 1 :]:
        if step[0] == "tick":
            await clock.increment(step[1])
        else:
            await i.send(step[1], **step[2])
    end = canon_snapshot(i.get_persisted_snapshot())
    await i.stop()
    return rec.actions, end, type(i.clock).__name__


def straight_sync(script, split):
    rec = Recorder()
    clock = SimulatedClock()
    i = SyncInterpreter(build(rec), clock=clock)
    i.start()
    mid, head = None, 0
    for k, step in enumerate(script):
        if step[0] == "tick":
            clock.increment(step[1])
        else:
            i.send(step[1], **step[2])
        if k == split:
            mid = i.get_persisted_snapshot()
            head = len(rec.actions)
    end = canon_snapshot(i.get_persisted_snapshot())
    i.stop()
    return rec.actions, mid, end, head


def resume_sync(script, split, mid_json):
    rec = Recorder()
    clock = SimulatedClock()
    i = SyncInterpreter.from_snapshot(mid_json, build(rec), clock=clock)
    i.start()
    for step in script[split + 1 :]:
        if step[0] == "tick":
            clock.increment(step[1])
        else:
            i.send(step[1], **step[2])
    end = canon_snapshot(i.get_persisted_snapshot())
    i.stop()
    return rec.actions, end, type(i.clock).__name__


def r2_dormant_timers():
    """Snapshot while parked in `armed` (an `after` is pending).

    MUST be called OUTSIDE a running event loop: `SimulatedClock.increment()`
    is a no-op-with-warning inside one (timers do not fire), which would make
    a passing library look broken.
    """
    out = {}
    clock = SimulatedClock()
    i = SyncInterpreter(timed_machine(), clock=clock)
    i.start()
    i.send("GO")
    raw = json.dumps(i.get_persisted_snapshot(), default=str)
    i.stop()

    static = SyncInterpreter.from_snapshot(raw, timed_machine())
    out["static_has_dormant_timers_before_start"] = getattr(
        static, "has_dormant_timers", "ATTR-MISSING"
    )
    static.start()
    out["static_has_dormant_timers_after_start"] = getattr(
        static, "has_dormant_timers", "ATTR-MISSING"
    )
    sc = SimulatedClock()
    static2 = SyncInterpreter.from_snapshot(raw, timed_machine(), clock=sc)
    static2.start()
    sc.increment(200)
    out["static_late_after_200ms"] = static2.context["late"]
    static2.stop()

    sc2 = SimulatedClock()
    re = SyncInterpreter.from_snapshot(
        raw, timed_machine(), clock=sc2, restart_timers=True
    )
    out["restart_has_dormant_timers_before_start"] = getattr(
        re, "has_dormant_timers", "ATTR-MISSING"
    )
    re.start()
    out["restart_has_dormant_timers_after_start"] = getattr(
        re, "has_dormant_timers", "ATTR-MISSING"
    )
    sc2.increment(200)
    out["restart_late_after_200ms"] = re.context["late"]
    out["restart_state_after_200ms"] = sorted(
        s.id for s in re._active_state_nodes if not s.states
    )
    re.stop()
    return out


async def amain():
    script = make_script(TOTAL)
    res = {}

    # R1/R3/R4 async
    acts, mid, end, head = await straight_async(script, SPLIT)
    mid_json = json.dumps(mid, default=str)
    ra, ea, clk = await resume_async(script, SPLIT, mid_json)
    ra2, ea2, _ = await resume_async(script, SPLIT, mid_json)
    res["async"] = {
        "restored_clock": clk,
        "resume_trace_len": len(ra),
        "straight_tail_len": len(acts) - head,
        "tail_actions_identical": ra == acts[head:],
        "final_snapshot_identical": ea == end,
        "resume_deterministic": ra == ra2 and ea == ea2,
    }

    acts, mid, end, head = straight_sync(script, SPLIT)
    mid_json = json.dumps(mid, default=str)
    rs, es, clks = resume_sync(script, SPLIT, mid_json)
    rs2, es2, _ = resume_sync(script, SPLIT, mid_json)
    res["sync"] = {
        "restored_clock": clks,
        "resume_trace_len": len(rs),
        "straight_tail_len": len(acts) - head,
        "tail_actions_identical": rs == acts[head:],
        "final_snapshot_identical": es == end,
        "resume_deterministic": rs == rs2 and es == es2,
    }

    res["R2_timers"] = "see main()"

    for k, v in res.items():
        print(f"\n== {k} ==")
        if isinstance(v, dict):
            for kk, vv in v.items():
                print(f"   {kk:42s}: {vv}")
    return res


def main():
    res = asyncio.run(amain())
    # 🧯 R2 runs OUTSIDE the loop -- SimulatedClock.increment() does not fire
    #    timers inside a running event loop.
    res["R2_timers"] = r2_dormant_timers()
    print("\n== R2_timers ==")
    for kk, vv in res["R2_timers"].items():
        print(f"   {kk:42s}: {vv}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "n2_clock_resume.json"), "w") as f:
        json.dump(res, f, indent=2, default=str)
    print("\nwrote out/n2_clock_resume.json")


if __name__ == "__main__":
    main()
