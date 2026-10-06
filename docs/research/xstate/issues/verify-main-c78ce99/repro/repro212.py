"""Standalone repro for #212: raise(delay=) self-send is a timer, not a
chain debt. A 1ms ping-pong heartbeat must run indefinitely past
maxIterations, on both engines and both def/async def action spellings.
Also checks the negative control: zero-delay raise WITHIN a step is still
bounded by maxIterations (that part of #206 must remain).
Run from neutral cwd (stdlib + xstate_statemachine only).
"""
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[3] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import asyncio
import json
import sys

sys.path.insert(
    0,
    str(_XS / 'src'),
)

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SimulatedClock,
    SyncInterpreter,
    create_machine,
)


def hb_cfg(delay_ms):
    arm = {"type": "raise", "params": {"event": "BEAT", "delay": delay_ms}}
    return {
        "id": "hb",
        "initial": "up",
        "maxIterations": 8,
        "context": {"n": 0},
        "states": {
            "up": {"entry": [arm, "beat"], "on": {"BEAT": "down"}},
            "down": {"entry": [arm, "beat"], "on": {"BEAT": "up"}},
        },
    }


def zero_delay_runaway_cfg():
    # Zero-delay raise self-ping-pong WITHIN one step: must still trip
    # RunawayChainError at maxIterations (this half of #206 is unchanged).
    return {
        "id": "zd",
        "initial": "up",
        "maxIterations": 8,
        "states": {
            "up": {
                "entry": [{"type": "raise", "params": {"event": "BEAT"}}],
                "on": {"BEAT": "down"},
            },
            "down": {
                "entry": [{"type": "raise", "params": {"event": "BEAT"}}],
                "on": {"BEAT": "up"},
            },
        },
    }


def mk(cfg, **kw):
    return create_machine(json.loads(json.dumps(cfg)), **kw)


def action(kind, body):
    if kind == "def":
        def plain(i, c, e, a):
            body(i, c)
        return plain

    async def coro(i, c, e, a):
        await asyncio.sleep(0)
        body(i, c)
    return coro


async def run_async(delay_ms, kind):
    logic = MachineLogic(
        actions={
            "beat": action(kind, lambda i, c: c.__setitem__("n", c["n"] + 1))
        }
    )
    i = await Interpreter(mk(hb_cfg(delay_ms), logic=logic)).start()
    await asyncio.sleep(1.5)
    n, err = i.context["n"], i.last_error
    await i.stop()
    return n, err


def run_sync(delay_ms, kind):
    logic = MachineLogic(
        actions={
            "beat": action(kind, lambda i, c: c.__setitem__("n", c["n"] + 1))
        }
    )
    s = SyncInterpreter(mk(hb_cfg(delay_ms), logic=logic)).start()
    import time

    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        s.tick()
        time.sleep(0.005)
    n, err = s.context["n"], s.last_error
    s.stop()
    return n, err


def zero_delay_trips():
    s = SyncInterpreter(mk(zero_delay_runaway_cfg())).start()
    ok = s.last_error is not None
    s.stop()
    return ok


if __name__ == "__main__":
    results = {}
    for kind in ("def", "async def"):
        n, err = asyncio.run(asyncio.wait_for(run_async(1, kind), 30))
        results[f"async-engine-1ms-{kind}"] = (n, str(err))
    n, err = run_sync(1, "def")
    results["sync-engine-1ms-def"] = (n, str(err))
    results["zero_delay_within_step_still_trips_runaway"] = zero_delay_trips()
    print(json.dumps(results, indent=2, default=str))
