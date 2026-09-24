"""R11-04 (STANDALONE): `_timer_handles` grows by exactly one retained entry per
`raise(delay=)` beat, on both engines, and nothing prunes it before `stop()`.

`Interpreter._schedule_send` registers the delayed-self-send handle as
`self._timer_handles.setdefault(self.id, []).append(handle)` -- keyed under the
INTERPRETER/MACHINE id. The only pruner runs on state exit and pops
`self._timer_handles.pop(state.id, [])`. The machine id is never an exiting
state, so the list is append-only for the interpreter's whole life. `_fire`
settles the send and clears `_armed_self_sends`/`_scheduled_sends` but leaves the
handle; `_cancel` clears the clock and `_armed_self_sends` but also leaves it.

The `after:` path registers under `owner_id=state.id` and IS pruned -- it is the
control below and it stays flat.

Before #212 this was capped: #206's chain trip killed a delayed self-send cycle
at ~`maxIterations` beats. #212 makes such a cycle a legal periodic process, so
the growth is now unbounded.

Exit 0 = handles/beat is ~0 on both spellings (defect fixed).
Exit 1 = `raise(delay=)` retains ~1.00 handle/beat while `after:` stays flat.

Stdlib + xstate_statemachine only. Runs from any cwd. Watchdog 60 s.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

from xstate_statemachine import (
    create_machine,
    Interpreter,
    SyncInterpreter,
    MachineLogic,
)

PERIOD_MS = 10
WINDOW_S = 5.0
LEAK_THRESHOLD = 0.5  # handles retained per beat


def raise_cfg() -> dict:
    """Ping-pong paced by a delayed self-send -- legal periodic work under #212."""
    arm = {"type": "raise", "params": {"event": "BEAT", "delay": PERIOD_MS}}
    return {
        "id": "leak",
        "initial": "up",
        "states": {
            "up": {"entry": [arm, "beat"], "on": {"BEAT": "down"}},
            "down": {"entry": [arm, "beat"], "on": {"BEAT": "up"}},
        },
    }


def after_cfg() -> dict:
    """Identical shape spelled with `after:` -- the leak-free control."""
    return {
        "id": "leak",
        "initial": "up",
        "states": {
            "up": {"entry": ["beat"], "after": {PERIOD_MS: "down"}},
            "down": {"entry": ["beat"], "after": {PERIOD_MS: "up"}},
        },
    }


def _handle_count(interp) -> int:
    return sum(len(v) for v in getattr(interp, "_timer_handles", {}).values())


async def run_async(cfg: dict, kind: str) -> dict:
    beats = {"n": 0}

    def _beat(i, c, e, a=None):  # noqa: ANN001  plain def
        beats["n"] += 1

    async def _beat_async(i, c, e, a=None):  # noqa: ANN001  async def
        beats["n"] += 1

    beat = _beat if kind == "def" else _beat_async

    machine = create_machine(cfg, logic=MachineLogic(actions={"beat": beat}))
    interp = Interpreter(machine)
    await interp.start()
    await asyncio.sleep(WINDOW_S)
    retained = _handle_count(interp)
    n = beats["n"]
    await interp.stop()
    return {
        "beats": n,
        "retained_handles": retained,
        "per_beat": round(retained / n, 4) if n else 0.0,
    }


def run_sync(cfg: dict) -> dict:
    beats = {"n": 0}

    def beat(i, c, e, a=None):  # noqa: ANN001
        beats["n"] += 1

    machine = create_machine(cfg, logic=MachineLogic(actions={"beat": beat}))
    interp = SyncInterpreter(machine)
    interp.start()
    # The sync engine has no run loop: it advances only when pumped. A NOOP the
    # chart does not declare is simply dropped, so it is a pure clock pump.
    t0 = time.time()
    while time.time() - t0 < WINDOW_S:
        time.sleep(0.004)
        interp.send("NOOP")
    retained = _handle_count(interp)
    n = beats["n"]
    interp.stop()
    return {
        "beats": n,
        "retained_handles": retained,
        "per_beat": round(retained / n, 4) if n else 0.0,
    }


async def main() -> int:
    results: dict = {}

    for kind in ("async def", "def"):
        results[f"ASYNC-ENGINE raise(delay=) / {kind}"] = await run_async(
            raise_cfg(), kind
        )
        results[f"ASYNC-ENGINE after: (control) / {kind}"] = await run_async(
            after_cfg(), kind
        )

    results["SYNC-ENGINE raise(delay=) / def"] = run_sync(raise_cfg())
    results["SYNC-ENGINE after: (control) / def"] = run_sync(after_cfg())

    print(json.dumps(results, indent=2))

    leaking = [
        cell
        for cell, r in results.items()
        if "raise(delay=)" in cell and r["per_beat"] >= LEAK_THRESHOLD
    ]
    controls_flat = all(
        r["per_beat"] < LEAK_THRESHOLD
        for cell, r in results.items()
        if "control" in cell
    )

    print()
    print(f"leaking raise(delay=) cells : {leaking}")
    print(f"after: controls all flat    : {controls_flat}")
    print(f"REPRODUCED: {bool(leaking) and controls_flat}")
    return 1 if leaking else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(asyncio.wait_for(main(), 60)))
    except asyncio.TimeoutError:
        print("WATCHDOG: exceeded 60 s")
        sys.exit(2)
