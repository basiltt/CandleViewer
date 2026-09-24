"""C14 — the async engine has NO runaway guard for an action-side `send()`.

CHANGELOG (#77) claims per-chain budget parity between the engines. It holds
for the `raise` BUILT-IN (both cut at max_iterations+1). It does NOT hold for
the other self-feeding shape the same CHANGELOG entry explicitly names:
"an action calling `send()` on its own interpreter".

* SyncInterpreter  : counted as self-generated -> chain broken at the limit.
* Interpreter(async): routed to the EXTERNAL inbox, never counted against
                      `_raise_depth` -> unbounded spin, forever.

Run: the sync machine returns; the async machine is still spinning after the
watchdog window and has executed far more than `max_iterations` steps.
"""

from __future__ import annotations

import asyncio
import warnings

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

warnings.simplefilter("ignore", DeprecationWarning)

CFG = {
    "id": "runaway",
    "initial": "run",
    "context": {"n": 0},
    "states": {"run": {"on": {"LOOP": {"actions": ["spin"]}}}},
}


def spin(i, c, e, a):
    c["n"] += 1
    i.send("LOOP")  # unconditional self-feed: a real bug in user code


def mk():
    return create_machine(CFG, logic=MachineLogic(actions={"spin": spin}))


async def main() -> None:
    limit = getattr(mk(), "max_iterations", 1000)
    print(f"machine.max_iterations = {limit}\n")

    # --- sync engine: the guard fires and send() returns -------------------
    s = SyncInterpreter(mk()).start()
    s.send("LOOP")
    print(f"SYNC : send() returned. steps = {s.context['n']}")
    s.stop()

    # --- async engine: no guard -------------------------------------------
    a = Interpreter(mk())
    await a.start()
    await a.send("LOOP")
    await asyncio.sleep(2.0)
    n2 = a.context["n"]
    print(f"ASYNC: after 2.0 s of spinning, steps = {n2}  status = {a.status}")
    await asyncio.sleep(1.0)
    n3 = a.context["n"]
    print(f"ASYNC: after 3.0 s, steps = {n3}  (still climbing: {n3 > n2})")
    print(f"ASYNC: queue_depth = {a.queue_depth}")
    await a.stop()

    assert s.context["n"] <= limit + 1, "sync guard did not fire"
    assert n3 > n2, "async chain terminated on its own"
    assert n3 > limit * 10, "async did not exceed the budget by a wide margin"
    print(
        "\nCONFIRMED: `max_iterations` bounds an action-side self-`send()` on\n"
        "SyncInterpreter only. The async engine spins forever -- the exact\n"
        "shape #77 names as budgeted. A CPU-pegged run loop, a growing inbox,\n"
        "and `status` still reporting 'running'."
    )


if __name__ == "__main__":
    asyncio.run(main())
