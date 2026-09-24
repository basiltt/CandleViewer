"""(d/g) The empty-configuration window during an async transition.

Found while running d1: at the instant a `SLOW` transition's async action
was mid-`await`, `interp.current_state_ids` was `set()` -- the machine
reported NO active state while `status == "running"`.

`_execute_transition` (base_interpreter.py:2328-2345) is explicit that
"exit -> actions -> enter is ONE transaction", and rolls back to
`snapshot_before` if an action raises, precisely so the configuration is
never left empty. That protects against FAILURE. It does not protect
against OBSERVATION: the transaction is not atomic with respect to the
event loop, so for as long as any action in the list is awaiting, every
other task on the loop sees the intermediate state.

This probe establishes:
  V1  the window is real and reachable from an ordinary concurrent reader
  V2  how long it lasts (bounded only by the action's own await)
  V3  which public surfaces expose it -- current_state_ids, state_ids(alias),
      matches(), get_snapshot(), get_persisted_snapshot(), plugin hooks
  V4  whether an event delivered during the window is handled or lost
  V5  whether a purely SYNCHRONOUS action list can produce the window
      (it cannot -- this is specific to actions that await)
"""

from __future__ import annotations

import asyncio
import time

from common import emit
from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

GATE: dict = {}

CFG = {
    "id": "win",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {
            "entry": ["mark_a"],
            "on": {
                "GO": {"target": "b", "actions": ["slow"]},
                "OTHER": {"actions": ["bump"]},
            },
        },
        "b": {"entry": ["mark_b"], "on": {"OTHER": {"actions": ["bump"]}}},
    },
}


async def slow(interpreter, ctx, event, action_def):  # noqa: ANN001
    GATE["entered"].set()
    await GATE["release"].wait()


def bump(interpreter, ctx, event, action_def):  # noqa: ANN001
    ctx["n"] += 1


def mark_a(interpreter, ctx, event, action_def):  # noqa: ANN001
    pass


def mark_b(interpreter, ctx, event, action_def):  # noqa: ANN001
    pass


def machine():
    return create_machine(
        CFG,
        logic=MachineLogic(
            actions={"slow": slow, "bump": bump, "mark_a": mark_a, "mark_b": mark_b}
        ),
    )


class Watcher(PluginBase):
    def __init__(self):
        self.transitions = []

    def on_transition(self, interpreter, from_states, to_states, transition):  # noqa: ANN001
        self.transitions.append((sorted(from_states), sorted(to_states)))


async def v1_v3_surfaces():
    GATE["entered"] = asyncio.Event()
    GATE["release"] = asyncio.Event()
    i = Interpreter(machine())
    w = Watcher()
    i.use(w)
    await i.start()
    before = sorted(i.current_state_ids)

    async def trigger():
        await i.send("GO")

    t = asyncio.create_task(trigger())
    await asyncio.wait_for(GATE["entered"].wait(), 5)

    # --- inside the window, from an ordinary concurrent task ---
    surfaces = {
        "current_state_ids": sorted(i.current_state_ids),
        "active_state_ids_alias": sorted(i.active_state_ids),
        "status": i.status,
        "matches_a": i.matches("a"),
        "matches_b": i.matches("b"),
    }
    try:
        snap = i.get_snapshot()
        surfaces["get_snapshot"] = str(snap)[:200]
    except Exception as exc:  # noqa: BLE001
        surfaces["get_snapshot"] = f"{type(exc).__name__}: {exc}"
    try:
        psnap = i.get_persisted_snapshot()
        surfaces["persisted_snapshot_state_ids"] = psnap.get("state_ids")
        surfaces["persisted_snapshot_status"] = psnap.get("status")
    except Exception as exc:  # noqa: BLE001
        surfaces["persisted_snapshot_error"] = f"{type(exc).__name__}: {exc}"

    # --- V4: is an event delivered during the window handled? ---
    await i.send("OTHER")
    n_during = i.context["n"]

    GATE["release"].set()
    await t
    await asyncio.sleep(0.05)

    return {
        "states_before": before,
        "in_window": surfaces,
        "context_n_during_window_send": n_during,
        "context_n_after": i.context["n"],
        "states_after": sorted(i.current_state_ids),
        "plugin_on_transition": w.transitions,
        "interp": i,
    }


async def v2_window_duration(await_s: float):
    """The window lasts as long as the action awaits -- show it scales."""
    GATE["entered"] = asyncio.Event()
    GATE["release"] = asyncio.Event()
    i = Interpreter(machine())
    await i.start()
    async def _go():
        await i.send("GO")

    t = asyncio.create_task(_go())
    await asyncio.wait_for(GATE["entered"].wait(), 10)
    t0 = time.perf_counter()
    empty_samples = 0
    samples = 0
    async def sampler():
        nonlocal empty_samples, samples
        while not GATE["release"].is_set():
            samples += 1
            if not i.current_state_ids:
                empty_samples += 1
            await asyncio.sleep(0.001)

    s = asyncio.create_task(sampler())
    await asyncio.sleep(await_s)
    GATE["release"].set()
    measured = time.perf_counter() - t0
    await s
    await t
    await asyncio.sleep(0.02)
    out = {
        "action_await_s": await_s,
        "window_observed_s": round(measured, 4),
        "samples": samples,
        "samples_with_empty_configuration": empty_samples,
        "states_after": sorted(i.current_state_ids),
    }
    await i.stop()
    return out


async def v5_sync_action_control():
    """A synchronous action list must NOT produce an observable window."""
    cfg = {
        "id": "sync",
        "initial": "a",
        "context": {"n": 0},
        "states": {
            "a": {"on": {"GO": {"target": "b", "actions": ["bump"]}}},
            "b": {},
        },
    }
    i = Interpreter(create_machine(cfg, logic=MachineLogic(actions={"bump": bump})))
    await i.start()
    empty_seen = 0
    stop = {"v": False}

    async def sampler():
        nonlocal empty_seen
        while not stop["v"]:
            if not i.current_state_ids:
                empty_seen += 1
            await asyncio.sleep(0)

    s = asyncio.create_task(sampler())
    for _ in range(200):
        await i.send("GO")
        await asyncio.sleep(0)
    await asyncio.sleep(0.05)
    stop["v"] = True
    await s
    out = {
        "sync_transitions": 200,
        "empty_configuration_observations": empty_seen,
        "states_after": sorted(i.current_state_ids),
    }
    await i.stop()
    return out


async def main():
    r1 = await v1_v3_surfaces()
    i = r1.pop("interp")
    await i.stop()
    emit(
        "probe_d_empty_window",
        {
            "v1_v3_surfaces": r1,
            "v2_window_10ms": await v2_window_duration(0.01),
            "v2_window_250ms": await v2_window_duration(0.25),
            "v5_sync_action_control": await v5_sync_action_control(),
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
