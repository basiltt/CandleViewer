"""LC-27 verification on xstate-statemachine 0.8.0.

Fix shipped (#48, #49, #50): `Clock` protocol, `RealClock` (default) and
`SimulatedClock` (virtual time) exported from the package; `Interpreter` /
`SyncInterpreter` accept `clock=`. Invoked/spawned children inherit the
parent's clock. This is additive -- `clock` is keyword-only with a
`RealClock` default, so default behaviour (no clock passed) is unchanged
(real wall-clock timers, as before).

We test:
  1. `clock` is now a constructor parameter (was: TypeError).
  2. `SimulatedClock` drives an `after` transition deterministically:
     incrementing virtual time fires it, with near-zero real wall time.
  3. Two timers (100ms, 200ms) fire in due order under one increment.
  4. Default clock (none passed) still uses real wall-clock time (no
     regression to existing behaviour).

Exit 0 if all hold, 1 otherwise.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time

from xstate_statemachine import Interpreter, MachineLogic, SimulatedClock, create_machine

logging.disable(logging.CRITICAL)

DELAY_MS = 600

CFG = {
    "id": "order",
    "initial": "submitting",
    "states": {
        "submitting": {"after": {DELAY_MS: {"target": "timed_out"}}},
        "timed_out": {"type": "final"},
    },
}


async def main() -> int:
    ok = True

    # 1) clock parameter exists.
    params = list(inspect.signature(Interpreter.__init__).parameters)
    print(f"OBSERVED Interpreter.__init__ params = {params}")
    print("EXPECTED a 'clock' parameter")
    if "clock" not in params:
        ok = False

    # 2) Passing a clock is accepted, no TypeError.
    machine = create_machine(CFG, logic=MachineLogic())
    clock = SimulatedClock()
    try:
        Interpreter(machine, clock=clock)
        print("OBSERVED Interpreter(machine, clock=...) accepted")
    except TypeError as exc:
        print(f"OBSERVED Interpreter(machine, clock=...) -> TypeError: {exc}")
        ok = False

    # 3) SimulatedClock drives `after` deterministically, ~0 wall time.
    clock2 = SimulatedClock()
    interp = await Interpreter(create_machine(CFG, logic=MachineLogic()), clock=clock2).start()
    started = time.monotonic()
    await clock2.increment(DELAY_MS - 1)
    fired_before = "order.timed_out" in interp.current_state_ids
    await clock2.increment(1)
    fired_after = "order.timed_out" in interp.current_state_ids
    elapsed_ms = (time.monotonic() - started) * 1000
    print(f"OBSERVED fired before full delay (increment({DELAY_MS - 1})) = {fired_before}")
    print("EXPECTED fired before full delay = False")
    print(f"OBSERVED fired after full delay (increment(1) more)        = {fired_after}")
    print("EXPECTED fired after full delay = True")
    print(f"OBSERVED real wall-clock time elapsed = {elapsed_ms:.1f} ms")
    print(f"EXPECTED ~0 ms under a simulated clock (real delay is {DELAY_MS} ms)")
    if fired_before or not fired_after or elapsed_ms >= DELAY_MS * 0.5:
        ok = False
    await interp.stop()

    # 4) Two timers fire in due order under one increment.
    order_seen = []
    cfg2 = {
        "id": "two",
        "type": "parallel",
        "states": {
            "a": {
                "initial": "wait",
                "states": {
                    "wait": {"after": {100: {"target": "done", "actions": ["mark_a"]}}},
                    "done": {"type": "final"},
                },
            },
            "b": {
                "initial": "wait",
                "states": {
                    "wait": {"after": {200: {"target": "done", "actions": ["mark_b"]}}},
                    "done": {"type": "final"},
                },
            },
        },
    }

    def mark_a(i, c, e, a):  # noqa: ANN001
        order_seen.append("a")

    def mark_b(i, c, e, a):  # noqa: ANN001
        order_seen.append("b")

    clock3 = SimulatedClock()
    interp2 = await Interpreter(
        create_machine(cfg2, logic=MachineLogic(actions={"mark_a": mark_a, "mark_b": mark_b})),
        clock=clock3,
    ).start()
    await clock3.increment(250)
    print(f"OBSERVED fire order = {order_seen}")
    print("EXPECTED fire order = ['a', 'b']")
    if order_seen != ["a", "b"]:
        ok = False
    await interp2.stop()

    # 5) Default clock (none passed) is still real wall-clock time.
    interp3 = await Interpreter(create_machine(CFG, logic=MachineLogic())).start()
    t0 = time.monotonic()
    while "order.timed_out" not in interp3.current_state_ids:
        await asyncio.sleep(0.01)
        if time.monotonic() - t0 > 3:
            break
    elapsed = (time.monotonic() - t0) * 1000
    print(f"OBSERVED default-clock real elapsed to fire = {elapsed:.0f} ms")
    print(f"EXPECTED ~{DELAY_MS} ms (unchanged real-time default behaviour)")
    if elapsed < DELAY_MS * 0.5:
        ok = False
    await interp3.stop()

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
