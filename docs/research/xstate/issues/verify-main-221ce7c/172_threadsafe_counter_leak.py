# -*- coding: utf-8 -*-
"""Verify #172 on main @ 221ce7c: `_threadsafe_self_sends_in_flight` balances
on every terminal outcome of a self-issued `send_threadsafe`, via a
done-callback on the returned `concurrent.futures.Future` (interpreter.py
`_threadsafe_self_send_settled`, added at the `fut.add_done_callback(...)`
call site), not just inside `_deliver`.

Criteria:
 1. A self-issued (`internal=True`) `send_threadsafe` whose coroutine never
    runs because the loop is stopped immediately after issue still balances
    the in-flight counter back to 0 (the exact leak shape from the issue:
    increment on the calling thread, no compensating decrement path).
 2. `_raise_depth` is not left permanently non-zero as a result (the
    downstream consequence the issue flags as latent).
 3. A self-issued send that DOES get delivered normally also balances to 0
    (no double-decrement / regression on the happy path).

Exit 0 if all criteria pass, 1 otherwise.
"""
import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {"id": "c", "initial": "a", "states": {"a": {"on": {"X": {"target": "a"}}}}}


async def check_leaked_path():
    """#172 criterion 1+2: coroutine never runs (loop stopped immediately)."""
    m = create_machine(CFG, logic=MachineLogic())
    i = Interpreter(m)
    await i.start()
    before = i._threadsafe_self_sends_in_flight
    fut = i.send_threadsafe("X", internal=True)
    await i.stop()  # the loop that would run `_deliver` is now gone
    await asyncio.sleep(0.05)  # let any pending done-callback fire
    after = i._threadsafe_self_sends_in_flight
    raise_depth = i._raise_depth
    return before, after, raise_depth


async def check_happy_path():
    """#172 criterion 3: normal delivery still balances to 0."""
    m = create_machine(CFG, logic=MachineLogic())
    i = Interpreter(m)
    await i.start()
    fut = i.send_threadsafe("X", internal=True)
    await asyncio.wrap_future(fut)
    await asyncio.sleep(0.05)
    after = i._threadsafe_self_sends_in_flight
    await i.stop()
    return after


def main():
    before, after_stop, raise_depth = asyncio.run(check_leaked_path())
    after_happy = asyncio.run(check_happy_path())

    print(f"leaked-path: before={before} after stop()={after_stop} raise_depth={raise_depth}")
    print(f"happy-path : in-flight after normal delivery={after_happy}")

    ok = True
    c1 = after_stop == 0
    print(f"[1] counter balances to 0 even when _deliver never runs: {c1}")
    ok &= c1

    c2 = raise_depth == 0
    print(f"[2] _raise_depth reset is not permanently gated off: {c2}")
    ok &= c2

    c3 = after_happy == 0
    print(f"[3] happy-path delivery still balances to 0 (no regression): {c3}")
    ok &= c3

    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
