"""VERIFY #218 on de2da4e (STANDALONE; stdlib + xstate_statemachine only).

Claim: timer handle released on fire/cancel for raise(delay=) self-sends, on
both engines. Handle count must stay flat (<=1 live handle) over a long
heartbeat (>=1000 beats), at several periods, plus a cancel path (state
exits before a delayed send fires).

Exit 0 = all cells pass. Exit 1 = any cell shows growth / leak.
"""
import asyncio
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.clock import SimulatedClock

N_BEATS = 1000


def _hb_cfg(period_ms, limit=100000):
    arm = {"type": "raise", "params": {"event": "BEAT", "delay": period_ms}}
    return {
        "id": "hb",
        "initial": "up",
        "maxIterations": limit,
        "context": {"n": 0},
        "states": {
            "up": {"entry": [arm, "beat"], "on": {"BEAT": "down"}},
            "down": {"entry": [arm, "beat"], "on": {"BEAT": "up"}},
        },
    }


def _handle_count(i):
    handles = getattr(i, "_timer_handles", {})
    return sum(len(v) for v in handles.values())


def _bump(i, c, e=None, ad=None):
    c["n"] = c.get("n", 0) + 1


async def _run_async(period_ms, act_kind):
    def act(i, c, e=None, ad=None):
        return _bump(i, c, e, ad)

    async def act_async(i, c, e=None, ad=None):
        _bump(i, c, e, ad)

    fn = act_async if act_kind == "async" else act
    clock = SimulatedClock()
    m = create_machine(
        _hb_cfg(period_ms), logic=MachineLogic(actions={"beat": fn})
    )
    i = Interpreter(m, clock=clock)
    await i.start()
    steps = 0
    while i.context.get("n", 0) < N_BEATS and steps < N_BEATS * 4 + 20:
        await clock.increment(period_ms + 0.5)
        steps += 1
    reached = i.context.get("n", 0) >= N_BEATS
    mid = _handle_count(i)
    await clock.increment(period_ms * 3 + 5)
    end = _handle_count(i)
    await i.stop()
    return reached, mid, end


def _run_sync(period_ms):
    clock = SimulatedClock()
    m = create_machine(
        _hb_cfg(period_ms), logic=MachineLogic(actions={"beat": _bump})
    )
    i = SyncInterpreter(m, clock=clock)
    i.start()
    steps = 0
    while i.context.get("n", 0) < N_BEATS and steps < N_BEATS * 4 + 20:
        clock.increment(period_ms + 0.5)
        steps += 1
    reached = i.context.get("n", 0) >= N_BEATS
    mid = _handle_count(i)
    clock.increment(period_ms * 3 + 5)
    end = _handle_count(i)
    i.stop()
    return reached, mid, end


_CANCEL_CFG = {
    "id": "cancel_path",
    "initial": "a",
    "states": {
        "a": {
            "entry": [
                {
                    "type": "raise",
                    "params": {"event": "X", "delay": 100000, "id": "k"},
                }
            ],
            "on": {
                "CUT": {
                    "actions": [{"type": "cancel", "params": {"sendId": "k"}}]
                }
            },
        }
    },
}


def _cancel_path_async():
    async def go():
        clock = SimulatedClock()
        m = create_machine(_CANCEL_CFG)
        i = Interpreter(m, clock=clock)
        await i.start()
        before = _handle_count(i)
        await i.send("CUT", wait=True)
        after = _handle_count(i)
        await i.stop()
        return before, after

    return asyncio.run(go())


def _cancel_path_sync():
    clock = SimulatedClock()
    m = create_machine(_CANCEL_CFG)
    i = SyncInterpreter(m, clock=clock)
    i.start()
    before = _handle_count(i)
    i.send("CUT")
    after = _handle_count(i)
    i.stop()
    return before, after


def main():
    fail = False
    for period in (1, 5, 20):
        for kind in ("def", "async"):
            reached, mid, end = asyncio.run(_run_async(period, kind))
            ok = mid <= 1 and end <= 1
            print(
                f"[async raise-delay period={period}ms kind={kind}] "
                f"reached={reached} mid={mid} end={end} {'OK' if ok else 'FAIL'}"
            )
            fail = fail or not ok

        reached_s, mid_s, end_s = _run_sync(period)
        ok_s = mid_s <= 1 and end_s <= 1
        print(
            f"[sync  raise-delay period={period}ms] reached={reached_s} "
            f"mid={mid_s} end={end_s} {'OK' if ok_s else 'FAIL'}"
        )
        fail = fail or not ok_s

    before, after = _cancel_path_async()
    ok = after == 0
    print(f"[async cancel-path] before={before} after={after} {'OK' if ok else 'FAIL'}")
    fail = fail or not ok

    before_s, after_s = _cancel_path_sync()
    ok_s = after_s == 0
    print(f"[sync  cancel-path] before={before_s} after={after_s} {'OK' if ok_s else 'FAIL'}")
    fail = fail or not ok_s

    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
