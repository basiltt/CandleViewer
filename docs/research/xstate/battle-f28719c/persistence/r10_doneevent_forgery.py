# -*- coding: utf-8 -*-
"""R10 -- MINIMAL: a user-constructed `DoneEvent` is indistinguishable from an
engine completion, and is not subject to `strict` / `onUnhandled`.

`Event` carries the #85 provenance sentinel and is checked. `DoneEvent` and
`AfterEvent` are `NamedTuple`s (`events.py:145`, `:453`) with **no
`_provenance` field and no `system` property at all** -- there is nothing to
forge because there is nothing to check. Any caller can construct
`DoneEvent(type="done.invoke.<id>", data=..., src=...)` and `send()` it.

This matters more after round 7 than before it, because #180 made
budget accounting *provenance*-based ("only engine completions and
self-raised events count") while #179 routed every real completion through
`_publish_completion`. The two questions this probe answers:

  A. Does a hand-built `DoneEvent` drive a real `onDone` transition -- i.e.
     can a caller fake a service result the service never produced?
  B. Is it exempt from `strict` / `onUnhandled: "error"`, which a plain
     `Event` of the same name is not?

Controls included: the same type as a plain `Event`; and the genuine
completion, so the forged and real paths are compared on one machine.
Both service kinds.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.events import AfterEvent, DoneEvent, Event

FAIL: list[str] = []

SPEC = {
    "id": "sec",
    "initial": "a",
    "strict": True,
    "onUnhandled": "error",
    "states": {
        "a": {
            "invoke": [{"id": "k", "src": "svc", "onDone": {"target": "done_"}}],
            "on": {"KNOWN": "b"},
        },
        "b": {},
        "done_": {},
    },
}


def build(kind: str, hang: bool):
    """`hang=True` -> the service never completes, so any arrival at
    `done_` is the FORGED event and nothing else."""

    def svc_def(i, c, e):  # noqa: ANN001
        if hang:
            import time

            time.sleep(30)
        return {"real": True}

    async def svc_async(i, c, e):  # noqa: ANN001
        if hang:
            await asyncio.sleep(30)
        return {"real": True}

    return create_machine(
        json.loads(json.dumps(SPEC)),
        logic=MachineLogic(
            services={"svc": svc_def if kind == "def" else svc_async}
        ),
    )


async def probe(kind: str, label: str, make_event, hang: bool = True) -> None:
    i = Interpreter(build(kind, hang), clock=SimulatedClock())
    await i.start(children_timeout=0.2)
    await asyncio.sleep(0.02)
    before = sorted(i.current_state_ids)
    ev = make_event()
    try:
        await i.send(ev)
        raised = None
    except Exception as exc:  # noqa: BLE001
        raised = type(exc).__name__
    await asyncio.sleep(0.05)
    after = sorted(i.current_state_ids)
    print("  [%-5s] %-34s %s -> %s  raised=%s status=%s"
          % (kind, label, before, after, raised, i.status))
    moved = after != before
    if label.startswith("FORGED") and moved:
        print("        ^ the forged completion DROVE the onDone transition "
              "while the real service is still running")
        FAIL.append(f"{kind}/{label}: forged DoneEvent drove onDone")
    if label.startswith("FORGED") and raised is None and i.status == "running" \
            and not moved:
        print("        ^ silently swallowed: strict did NOT reject it and "
              "onUnhandled:'error' did NOT fire")
        FAIL.append(f"{kind}/{label}: forged event exempt from strict")
    await i.stop()


async def main() -> None:
    print("machine: strict=True, onUnhandled='error', invoke k with onDone\n"
          "service HANGS, so reaching 'done_' can only be the forged event\n")
    for kind in ("def", "async"):
        # control A: the real completion (service returns) does move the machine
        await probe(kind, "control: real completion",
                    lambda: Event(type="KNOWN"), hang=False)
        # control B: a plain Event of the same name is enforced
        await probe(kind, "control: Event('done.invoke.k')",
                    lambda: Event(type="done.invoke.k"))
        # the attack
        await probe(kind, "FORGED DoneEvent('done.invoke.k')",
                    lambda: DoneEvent(type="done.invoke.k",
                                      data={"forged": True}, src="k"))
        # and the timer twin
        await probe(kind, "FORGED AfterEvent",
                    lambda: AfterEvent(type="after.50.sec.a"))
        # a DoneEvent for a service that does not exist at all
        await probe(kind, "FORGED DoneEvent(no such actor)",
                    lambda: DoneEvent(type="done.invoke.NOPE",
                                      data={}, src="NOPE"))
        print()

    print("surface check:")
    d = DoneEvent(type="done.invoke.k", data={}, src="k")
    a = AfterEvent(type="after.1.x")
    e = Event(type="X")
    for nm, o in (("DoneEvent", d), ("AfterEvent", a), ("Event", e)):
        print("  %-11s has .system=%-5s has ._provenance=%-5s type=%s"
              % (nm, hasattr(o, "system"), hasattr(o, "_provenance"),
                 type(o).__mro__[1].__name__))

    print("\nFAILURES:", FAIL if FAIL else "none")
    print("VERDICT:", "FAIL" if FAIL else "PASS")


asyncio.run(main())
