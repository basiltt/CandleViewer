"""N-01 repro: `send(event, wait=True)` hangs forever on a reused `Event`.

`_make_receipt` / `_resolve_receipt` key the pending-receipt map on
`id(event_obj)`. Two concurrent `send(ev, wait=True)` calls that pass the *same*
`Event` instance collide on that key: the second `_make_receipt` overwrites the
first future, which is then never resolved and never failed. The awaiting
coroutine hangs with no error and no timeout.

Controls included, so the finding cannot be misattributed:
  * fresh objects, 2-way concurrent  -> both resolve
  * fresh objects, 200-way concurrent -> all resolve (id() recycling is NOT it)
  * same object, sequential           -> resolves

Exit 1 while the defect is present, 0 once it is fixed.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import Event, Interpreter, create_machine

logging.disable(logging.CRITICAL)

CFG = {
    "id": "rc",
    "initial": "a",
    "states": {
        "a": {"on": {"T": {"target": "b"}}},
        "b": {"on": {"T": {"target": "a"}}},
    },
}

TIMEOUT = 3.0


async def _fresh(interp: Interpreter, n: int) -> str:
    try:
        await asyncio.wait_for(
            asyncio.gather(*(interp.send("T", wait=True) for _ in range(n))),
            timeout=TIMEOUT,
        )
        return "resolved"
    except asyncio.TimeoutError:
        return "HUNG"


async def _same_object_sequential(interp: Interpreter) -> str:
    ev = Event(type="T", payload={})
    try:
        await asyncio.wait_for(interp.send(ev, wait=True), timeout=TIMEOUT)
        await asyncio.wait_for(interp.send(ev, wait=True), timeout=TIMEOUT)
        return "resolved"
    except asyncio.TimeoutError:
        return "HUNG"


async def _same_object_concurrent(interp: Interpreter) -> str:
    ev = Event(type="T", payload={})
    try:
        await asyncio.wait_for(
            asyncio.gather(interp.send(ev, wait=True), interp.send(ev, wait=True)),
            timeout=TIMEOUT,
        )
        return "resolved"
    except asyncio.TimeoutError:
        return "HUNG"


async def main() -> int:
    results: dict[str, str] = {}

    for label, coro in (
        ("control_fresh_2way", lambda i: _fresh(i, 2)),
        ("control_fresh_200way", lambda i: _fresh(i, 200)),
        ("control_same_object_sequential", _same_object_sequential),
        ("subject_same_object_concurrent", _same_object_concurrent),
    ):
        interp = Interpreter(create_machine(CFG))
        await interp.start()
        try:
            results[label] = await coro(interp)
        finally:
            try:
                await asyncio.wait_for(interp.stop(), timeout=2.0)
            except Exception:  # noqa: BLE001 - teardown must not mask the result
                pass

    for k, v in results.items():
        print(f"OBSERVED {k:<32}: {v}")
    print("EXPECTED every case                    : resolved")

    reproduced = (
        results["control_fresh_2way"] == "resolved"
        and results["control_fresh_200way"] == "resolved"
        and results["control_same_object_sequential"] == "resolved"
        and results["subject_same_object_concurrent"] == "HUNG"
    )
    if reproduced:
        print("RESULT: DEFECT REPRODUCED")
        return 1
    if all(v == "resolved" for v in results.values()):
        print("RESULT: NOT REPRODUCED (fixed)")
        return 0
    print("RESULT: INCONCLUSIVE - a control did not behave as expected")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
