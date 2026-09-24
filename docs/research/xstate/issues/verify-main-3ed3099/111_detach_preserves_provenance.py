# -*- coding: utf-8 -*-
"""Verify #111 on 3ed3099: Interpreter._detach() preserves an Event's
provenance marker (`_provenance`), so `send(engine_event, wait=True)` is
still treated as system traffic, matching `send(engine_event, wait=False)`.

Criteria (from issue body + CHANGELOG #111):
  1. wait=False on an engine-minted event (system_event(...)) -> status
     stays "running" (honoured as system traffic; unaffected either way).
  2. wait=True on the SAME kind of engine-minted event -> ALSO status
     stays "running" (no demotion to user traffic).
  3. `Event._detach` fabricates a genuinely distinct object (per #75) while
     still reporting `.system is True` on the copy.
  4. The marker survives even when `_detach`'s dataclasses.replace() path
     is used (verified indirectly via criterion 2, since only Event
     instances take that path).

Exits 0 iff all pass.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import system_event

CFG = {
    "id": "m",
    "initial": "a",
    "onUnhandled": "error",
    "states": {"a": {"on": {"GO": "b"}}, "b": {}},
}


async def run(wait: bool) -> str:
    interp = Interpreter(create_machine(CFG, logic=MachineLogic()))
    await interp.start()
    await interp.send(
        system_event("xstate.error.actor.child", error="boom"), wait=wait
    )
    await asyncio.sleep(0.2)
    status = interp.status
    if status == "running":
        await interp.stop()
    return status


def check_detach_identity_and_marker() -> bool:
    from xstate_statemachine.interpreter import Interpreter as _I

    ev = system_event("xstate.status", note="x")
    fresh = _I._detach(ev)
    ok_distinct = fresh is not ev
    ok_marker = fresh.system is True and ev.system is True
    print(
        f"[detach_identity] distinct object={ok_distinct} "
        f"marker preserved={ok_marker}"
    )
    return ok_distinct and ok_marker


async def main() -> int:
    status_false = await run(False)
    status_true = await run(True)
    print(f"wait=False -> status={status_false}")
    print(f"wait=True  -> status={status_true}")

    results = [
        status_false == "running",
        status_true == "running",
        check_detach_identity_and_marker(),
    ]
    n_ok = sum(results)
    print(f"\n{n_ok}/{len(results)} criteria passed")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
