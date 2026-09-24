"""R6-15: `stop()` is supposed to resolve EVERY outstanding receipt --
including receipts for duplicate `Event`-instance sends (the #75 fix
detaches the queued copy so two concurrent `send(same_event, wait=True)`
calls no longer collide in the receipt map) -- with `InterpreterStoppedError`.

Cases A, B, C of the original duplicate-instance collision bug (fresh
instances concurrent; same instance sequential; two concurrent SEPARATE
instances) are confirmed fixed elsewhere and are not retested here. This
script targets case D specifically: two concurrent `send()` calls that
reuse the SAME `Event` instance, raced against `stop()`. Some of them
should land on `InterpreterStoppedError`; if any lands as an ordinary
success `Receipt`, the invariant "nothing after stop() succeeds" is
violated for a caller relying on the receipt to know whether their action
had any effect.

Run: python R6-15_stop_leaves_duplicate_receipts_unresolved.py
Expect (bug present): at least one of the racing duplicate-instance sends
  resolves as an ordinary success `Receipt` (error is None, changed=True)
  despite racing `stop()`, over several repeated trials.
"""
import asyncio
import sys

from xstate_statemachine import Event, Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import InterpreterStoppedError


CFG = {
    "id": "sd",
    "initial": "a",
    "states": {
        "a": {"on": {"T": {"target": "a"}}},
    },
}


async def one_trial(n_racers: int):
    m = create_machine(CFG, logic=MachineLogic())
    i = Interpreter(m)
    await i.start()

    ev = Event(type="T", payload={})

    async def racer():
        try:
            return await i.send(ev, wait=True)
        except Exception as exc:  # pragma: no cover - defensive
            return exc

    tasks = [asyncio.create_task(racer()) for _ in range(n_racers)]
    # Let the run loop pick up and start processing the queued duplicate
    # sends before stop() races in -- this is the window where #75's
    # detached-copy receipts are outstanding but not yet resolved.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    stop_task = asyncio.create_task(i.stop())
    results = await asyncio.gather(*tasks, stop_task, return_exceptions=True)
    receipts = results[:-1]

    ok_success = []
    ok_stopped = []
    other = []
    for r in receipts:
        if isinstance(r, Exception):
            other.append(r)
            continue
        if r.error is not None and isinstance(r.error, InterpreterStoppedError):
            ok_stopped.append(r)
        elif r.error is None:
            ok_success.append(r)
        else:
            other.append(r)

    return ok_success, ok_stopped, other


async def main():
    n_racers = 8
    n_trials = 20
    total_success_despite_stop = 0

    for trial in range(n_trials):
        ok_success, ok_stopped, other = await one_trial(n_racers)
        total_success_despite_stop += len(ok_success)
        if trial < 3 or ok_success:
            print(
                f"trial {trial}: success_despite_stop_race={len(ok_success)} "
                f"resolved_stopped={len(ok_stopped)} other={len(other)}"
            )

    print(f"total success-despite-stop-race receipts across {n_trials} trials: "
          f"{total_success_despite_stop}")

    bug_present = total_success_despite_stop > 0
    if bug_present:
        print(
            "BUG CONFIRMED: at least one duplicate-Event-instance receipt "
            "raced past stop() and resolved as an ordinary success Receipt "
            "instead of being resolved with InterpreterStoppedError."
        )
        sys.exit(1)
    else:
        print("Not reproduced: every racing duplicate-instance receipt "
              "resolved with InterpreterStoppedError.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
