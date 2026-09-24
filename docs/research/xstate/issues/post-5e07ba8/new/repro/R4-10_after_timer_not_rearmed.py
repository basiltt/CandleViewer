# -*- coding: utf-8 -*-
"""R4-10: `after` timers are never re-armed by `from_snapshot()`, in either
`restart_services` mode, and there is no dormancy signal for a lost timer.

Standalone: no harness import. Uses a small local `attach_clock` helper
copied from `battle-5e07ba8/persistence/harness.py`, since `from_snapshot()`
has no `clock=` parameter.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.base_interpreter import _accepts_kwarg
from xstate_statemachine.clock import SimulatedClock

CONFIG = {
    "id": "timeout_demo",
    "initial": "waiting",
    "context": {"fired": False},
    "states": {
        "waiting": {
            "after": {"5000": {"target": "expired", "actions": ["mark"]}},
            "on": {"OK": {"target": "done_ok"}},
        },
        "expired": {"type": "final"},
        "done_ok": {"type": "final"},
    },
}


def mark(interp, ctx, event, ad):  # noqa: ANN001
    ctx["fired"] = True


def build():
    return create_machine(CONFIG, logic=MachineLogic(actions={"mark": mark}))


def attach_clock(interp, clock: SimulatedClock) -> None:
    interp.clock = clock
    interp._clock_accepts_sync = _accepts_kwarg(clock.set_timeout, "sync")
    clock._attach(interp._settle_for_clock)


async def main() -> int:
    # --- reference: no crash -------------------------------------------
    c1 = SimulatedClock()
    i1 = await Interpreter(build(), clock=c1).start()
    await asyncio.sleep(0.02)
    await c1.increment(6000)
    await asyncio.sleep(0.02)
    ref_states = sorted(i1.current_state_ids)
    ref_fired = i1.context["fired"]
    print("REFERENCE  after 6 s :", ref_states, "fired =", ref_fired)
    await i1.stop()

    results = {}
    for restart in (False, True):
        c2 = SimulatedClock()
        i2 = await Interpreter(build(), clock=c2).start()
        await asyncio.sleep(0.02)
        await c2.increment(1000)
        blob = i2.get_snapshot()
        now = c2.now()
        await i2.stop()

        c3 = SimulatedClock()
        c3._now = now  # virtual time survives the crash
        i3 = Interpreter.from_snapshot(blob, build(), restart_services=restart)
        attach_clock(i3, c3)
        await i3.start()
        await asyncio.sleep(0.02)
        print(
            f"  restart_services={restart}: "
            f"dormant={i3.has_dormant_invocations} "
            f"pending_invocations={i3.pending_invocations()} "
            f"clock.pending={c3.pending}"
        )
        await c3.increment(10000)  # 11 s total -- well past the 5 s deadline
        await asyncio.sleep(0.02)
        states = sorted(i3.current_state_ids)
        fired = i3.context["fired"]
        print(
            f"  RESTORED after 11 s: {states} fired = {fired} status={i3.status}"
        )
        results[restart] = (states, fired)
        await i3.stop()

    print(
        "EXPECTED: both restores reach ['timeout_demo.expired'] with fired=True, "
        "matching the reference run."
    )
    ok = all(states == ["timeout_demo.expired"] and fired for states, fired in results.values())
    print("RESULT:", "PASS" if ok else "FAIL (after timer lost across restore)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
