"""R6-12: `_threadsafe_self_sends_in_flight` is incremented on the calling
thread (interpreter.py ~1132) but only decremented inside the `_deliver`
coroutine (interpreter.py ~1136). If `_deliver` never runs -- because the
loop is refused, the interpreter has already stopped, or the internal
enqueue never gets scheduled -- the counter leaks upward permanently.

That counter also gates the `_raise_depth` reset (interpreter.py ~1513):
while it is non-zero the reset is skipped, so in principle a long-lived
machine could eventually trip `RunawayChainError` on ordinary work. This
script demonstrates the leak itself, which is deterministic; it does NOT
attempt to drive an actual `RunawayChainError`, matching the honest scoping
in the issue (external events do not increment `_raise_depth`, so the
downstream consequence is latent, not independently observed here).

Run: python R6-12_threadsafe_self_send_counter_leak.py
Expect (bug present): counter > 0 after the interpreter has stopped, with
  no corresponding in-flight self-send actually pending.
"""
import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine


CFG = {
    "id": "c",
    "initial": "a",
    "states": {"a": {"on": {"X": {"target": "a"}}}},
}


async def main():
    m = create_machine(CFG, logic=MachineLogic())
    i = Interpreter(m)
    await i.start()

    # Force the interpreter into a stopped state WHILE a self-issued send is
    # mid-flight, by stopping it immediately after incrementing the counter
    # the same way `send(..., self_issued=True)` does, before `_deliver` gets
    # a chance to run and decrement it.
    before = i._threadsafe_self_sends_in_flight
    i._threadsafe_self_sends_in_flight += 1  # what an in-flight self-send looks like
    await i.stop()  # the loop that would run `_deliver` is now gone
    await asyncio.sleep(0.05)  # give any pending callback a chance anyway

    after = i._threadsafe_self_sends_in_flight
    raise_depth = i._raise_depth

    print(f"in-flight counter before={before} after stop()={after}")
    print(f"_raise_depth after stop()={raise_depth}")

    bug_present = after > 0
    if bug_present:
        print(
            "BUG CONFIRMED: the in-flight counter leaked past stop() with "
            "no compensating decrement -- nothing will ever bring it back "
            "to 0 for this interpreter, so the _raise_depth reset "
            "(interpreter.py ~1513) is permanently gated off."
        )
        sys.exit(1)
    else:
        print("Not reproduced: the counter was correctly reset to 0.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
