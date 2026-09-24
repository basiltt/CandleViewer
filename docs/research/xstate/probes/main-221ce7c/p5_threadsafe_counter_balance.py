"""L-5 probe: the #172 in-flight counter is a non-atomic read-modify-write
touched from many threads.

`self._threadsafe_self_sends_in_flight += 1` runs on the CALLING worker
thread; the balancing `-= 1` runs from a `concurrent.futures.Future`
done-callback, which fires on whichever thread completed the future (the
loop thread for a normal delivery). Two plain `+=`/`-=` on an int attribute
are not atomic under free-threading and are only incidentally atomic under
the GIL for a *slot* attribute. More importantly the counter can go
NEGATIVE or leak, and a leaked/negative value gates the `_raise_depth`
reset (the exact failure #172 was filed for).

This probe hammers send_threadsafe(internal=True) from N threads and checks
the counter settles to exactly 0.
"""

import asyncio
import threading

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CONFIG = {
    "id": "p5",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"T": {"actions": ["bump"]}}}},
}


def bump(interp, ctx, ev, action_def):  # noqa: ANN001
    ctx["n"] += 1


async def main() -> None:
    m = create_machine(CONFIG, logic=MachineLogic(actions={"bump": bump}))
    interp = Interpreter(m)
    await interp.start()

    THREADS, PER = 8, 500
    errs = []

    def worker() -> None:
        for _ in range(PER):
            try:
                interp.send_threadsafe("T", internal=True)
            except Exception as exc:  # noqa: BLE001
                errs.append(exc)

    ts = [threading.Thread(target=worker) for _ in range(THREADS)]
    for t in ts:
        t.start()
    while any(t.is_alive() for t in ts):
        await asyncio.sleep(0.01)
    for t in ts:
        t.join()

    for _ in range(400):
        await asyncio.sleep(0.01)
        if (
            interp.context["n"] >= THREADS * PER
            and interp._threadsafe_self_sends_in_flight == 0
        ):
            break

    n = interp.context["n"]
    c = interp._threadsafe_self_sends_in_flight
    print(f"sent={THREADS*PER} processed={n} errors={len(errs)}")
    print(f"in_flight_counter={c} (expected 0)")
    print(f"_raise_depth={interp._raise_depth} chain_tripped={interp._chain_tripped}")
    print(
        "VERDICT:",
        "balanced" if c == 0 else f"COUNTER UNBALANCED ({c}) -- gates chain reset",
    )
    try:
        await asyncio.wait_for(interp.stop(), timeout=5)
    except Exception:  # noqa: BLE001
        print("stop() timed out")


asyncio.run(main())
