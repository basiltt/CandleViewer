"""K-5 refined: with the loop genuinely stalled, does internal=True from a
foreign thread bypass the bounded inbox + OverflowPolicy.RAISE?"""
import asyncio
import threading

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    create_machine,
)
from xstate_statemachine.exceptions import QueueOverflowError

CFG = {
    "id": "b",
    "initial": "a",
    "states": {"a": {"on": {"STALL": {"actions": ["stall"]}, "X": "a"}}},
}


async def main():
    gate = threading.Event()

    async def stall(i, c, e, a):
        # hold the run loop hostage until the producer has finished
        await asyncio.get_running_loop().run_in_executor(None, gate.wait)

    m = create_machine(CFG, logic=MachineLogic(actions={"stall": stall}))
    i = Interpreter(m, max_queue_size=2, overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    await i.send("STALL")
    await asyncio.sleep(0.1)  # let the stall action take hold

    honest_ok = honest_refused = 0
    forged_ok = forged_refused = 0

    def producer():
        nonlocal honest_ok, honest_refused, forged_ok, forged_refused
        for _ in range(50):
            try:
                i.send_threadsafe("X")
                honest_ok += 1
            except QueueOverflowError:
                honest_refused += 1
        for _ in range(5000):
            try:
                i.send_threadsafe("X", internal=True)
                forged_ok += 1
            except QueueOverflowError:
                forged_refused += 1

    t = threading.Thread(target=producer)
    t.start()
    await asyncio.get_running_loop().run_in_executor(None, t.join)
    print(f"inbox max=2, policy=RAISE, loop stalled")
    print(f"  honest send_threadsafe : accepted={honest_ok} refused={honest_refused}")
    print(f"  internal=True          : accepted={forged_ok} refused={forged_refused}")
    print(f"  in_flight counter      : {i._threadsafe_self_sends_in_flight}")
    gate.set()
    await asyncio.sleep(0.5)
    print(f"  after release: status={i.status} "
          f"err={type(i.error).__name__ if i.error else None} "
          f"internal_q={len(i._internal_queue)}")
    await i.stop()


if __name__ == "__main__":
    asyncio.run(main())
