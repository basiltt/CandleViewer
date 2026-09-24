"""i1: #212 semantics matrix -- delayed raise(delay=) self-ping-pong runs
indefinitely past maxIterations (legal periodic process, must NOT trip),
CPU bounded by clock period; a zero-delay raise ping-pong (unchanged
behaviour) must still trip RunawayChainError. Both engines (Interpreter /
SyncInterpreter). Follows the pinned test_round10_findings.py pattern.
"""
import asyncio
import json
import time

from xstate_statemachine import Interpreter, SyncInterpreter, create_machine, MachineLogic
from xstate_statemachine.exceptions import RunawayChainError


def raise_cfg(delay):
    arm_up = {"type": "raise", "params": {"event": "BEAT", "delay": delay}}
    return {
        "id": "hb",
        "initial": "up",
        "maxIterations": 8,
        "context": {"n": 0},
        "states": {
            "up": {"entry": [arm_up, "beat"], "on": {"BEAT": "down"}},
            "down": {"entry": [arm_up, "beat"], "on": {"BEAT": "up"}},
        },
    }


def zero_cfg():
    arm = {"type": "raise", "params": {"event": "BEAT"}}
    return {
        "id": "hb0",
        "initial": "up",
        "maxIterations": 50,
        "context": {"n": 0},
        "states": {
            "up": {"entry": [arm, "beat"], "on": {"BEAT": "down"}},
            "down": {"entry": [arm, "beat"], "on": {"BEAT": "up"}},
        },
    }


def beat(i, c, *_):
    c["n"] = c["n"] + 1


def run_async_delayed(period_ms):
    async def main():
        m = create_machine(raise_cfg(period_ms), logic=MachineLogic(actions={"beat": beat}))
        i = await Interpreter(m).start()
        await asyncio.sleep(1.0)
        n, err = i.context["n"], i.last_error
        await i.stop()
        return n, err

    return asyncio.run(main())


def run_sync_delayed(period_ms):
    m = create_machine(raise_cfg(period_ms), logic=MachineLogic(actions={"beat": beat}))
    i = SyncInterpreter(m)
    i.start()
    t0 = time.time()
    while time.time() - t0 < 1.0:
        i.tick()
        time.sleep(0.001)
    n, err = i.context["n"], i.last_error
    i.stop()
    return n, err


def run_async_zero():
    async def main():
        m = create_machine(zero_cfg(), logic=MachineLogic(actions={"beat": beat}))
        tripped = False
        err = None
        i = Interpreter(m)
        try:
            await i.start()
            await asyncio.sleep(0.3)
        except RunawayChainError as e:
            tripped = True
            err = str(e)
        if not tripped and i.last_error is not None:
            tripped = True
            err = str(i.last_error)
        await i.stop()
        return tripped, err

    return asyncio.run(main())


def run_sync_zero():
    m = create_machine(zero_cfg(), logic=MachineLogic(actions={"beat": beat}))
    i = SyncInterpreter(m)
    tripped = False
    err = None
    try:
        i.start()
    except RunawayChainError as e:
        tripped = True
        err = str(e)
    if not tripped and i.last_error is not None:
        tripped = True
        err = str(i.last_error)
    return tripped, err


if __name__ == "__main__":
    out = {}

    # 30ms period (matches pinned test cell), 1s window -> expect >=30 beats
    n_a, err_a = run_async_delayed(30)
    n_s, err_s = run_sync_delayed(30)
    out["delayed_30ms_1s_window"] = {
        "async_n": n_a, "async_err": err_a,
        "sync_n": n_s, "sync_err": err_s,
        "must_not_trip": err_a is None and err_s is None,
        "must_exceed_maxIterations": n_a >= 30 and n_s >= 8,
    }

    # 1ms period ping-pong -- the exact case #212 legalises
    t0 = time.time()
    n_a1, err_a1 = run_async_delayed(1)
    dt_a = time.time() - t0
    t0 = time.time()
    n_s1, err_s1 = run_sync_delayed(1)
    dt_s = time.time() - t0
    out["delayed_1ms_1s_window"] = {
        "async_n": n_a1, "async_err": err_a1, "async_wall_s": round(dt_a, 3),
        "sync_n": n_s1, "sync_err": err_s1, "sync_wall_s": round(dt_s, 3),
        "must_not_trip": err_a1 is None and err_s1 is None,
        "beats_bounded_by_clock": n_a1 < 5000 and n_s1 < 5000,  # not a busy-loop explosion
    }

    # zero-delay control: must still trip
    trip_a, e_a = run_async_zero()
    trip_s, e_s = run_sync_zero()
    out["zero_delay_control"] = {
        "async_tripped": trip_a, "async_err": e_a,
        "sync_tripped": trip_s, "sync_err": e_s,
        "must_trip_both": trip_a and trip_s,
    }

    print(json.dumps(out, indent=2))
