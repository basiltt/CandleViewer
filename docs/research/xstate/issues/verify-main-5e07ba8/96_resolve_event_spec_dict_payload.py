"""Verify #96 on xstate-statemachine @ 5e07ba8 (unreleased 0.8.1).

Acceptance criteria (from `gh issue view 96`):
  1. Resolving an `ErrorEvent` through `_resolve_event_spec` yields an event
     whose `payload` is a mapping, or preserves the `ErrorEvent`.
  2. `sendParent` forwarding a triggering `ErrorEvent` delivers something the
     parent can read with `.get()` or with `isinstance(event, ErrorEvent)`.
  3. No `DeprecationWarning` is emitted from this site.
  4. Test: `test_resolve_event_spec_errorevent_payload_is_mapping` (library's
     own equivalent: `test_resolve_event_spec_always_yields_dict_payload`).

Run: PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/Scripts/python -W error::DeprecationWarning 96_resolve_event_spec_dict_payload.py
Expect: exit 0, "ALL CRITERIA PASS".
"""
import asyncio
import sys
import warnings

from xstate_statemachine import (
    Event,
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.events import AfterEvent, DoneEvent, ErrorEvent

failures = []

# --- Criterion 1 + 3: unit-level _resolve_event_spec always yields a dict payload
it = SyncInterpreter(create_machine({"id": "t", "initial": "a", "states": {"a": {}}}))
it.start()

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    for src in (
        ErrorEvent("error.platform.svc", ValueError("boom"), "svc"),
        DoneEvent("done.invoke.svc", {"k": 1}, "svc"),
        DoneEvent("done.invoke.svc", 42, "svc"),
        AfterEvent("after.5"),
    ):
        ev = it._resolve_event_spec(src, Event("X"))
        if not isinstance(ev.payload, dict):
            failures.append(
                f"criterion 1: {type(src).__name__} -> payload type "
                f"{type(ev.payload).__name__}, expected dict"
            )
    err_ev = it._resolve_event_spec(
        ErrorEvent("error.platform.svc", ValueError("boom"), "svc"), Event("X")
    )
    if not isinstance(err_ev.payload.get("error"), ValueError):
        failures.append("criterion 1: ErrorEvent payload does not carry the exception under 'error'")

dep = [w for w in caught if issubclass(w.category, DeprecationWarning)]
if dep:
    failures.append(f"criterion 3: DeprecationWarning raised: {[str(w.message) for w in dep]}")

it.stop()

# --- Criterion 2: end-to-end sendParent forwarding of a triggering ErrorEvent
child = {
    "id": "c",
    "initial": "w",
    "actionErrorPolicy": "continue",
    "states": {
        "w": {
            "invoke": {
                "src": "svc",
                "id": "svc",
                "onError": {
                    "target": "err",
                    "actions": [
                        {
                            "type": "sendParent",
                            "params": {"event": lambda a: a["event"]},
                        }
                    ],
                },
            }
        },
        "err": {},
    },
}
parent = {
    "id": "p",
    "initial": "w",
    "states": {
        "w": {
            "invoke": {"src": "kid", "id": "kid"},
            "on": {"error.platform.svc": {"target": "caught", "actions": "look"}},
        },
        "caught": {},
    },
}

seen = {}


async def blow(i, c, e):
    raise ValueError("boom")


async def main():
    p = await Interpreter(
        create_machine(
            parent,
            logic=MachineLogic(
                services={"kid": create_machine(child, logic=MachineLogic(services={"svc": blow}))},
                actions={"look": lambda i, c, e, a: seen.update(ev=e)},
            ),
        )
    ).start()
    await asyncio.sleep(0.2)
    st = p.value
    await p.stop()
    return st


with warnings.catch_warnings(record=True) as caught2:
    warnings.simplefilter("always")
    val = asyncio.run(main())

dep2 = [
    w
    for w in caught2
    if issubclass(w.category, DeprecationWarning)
    and "ErrorEvent" in str(w.message)
]
if dep2:
    failures.append(f"criterion 3 (e2e): DeprecationWarning raised: {[str(w.message) for w in dep2]}")

ev = seen.get("ev")
if ev is None:
    failures.append("criterion 2: parent handler never fired (forwarded event not delivered)")
elif isinstance(ev, ErrorEvent):
    pass  # preserved as ErrorEvent -- acceptable per criterion 1's "or preserves"
elif hasattr(ev, "payload") and isinstance(ev.payload, dict):
    try:
        ev.payload.get("error")
    except AttributeError:
        failures.append("criterion 2: forwarded event payload.get() raised AttributeError")
else:
    failures.append(f"criterion 2: forwarded event not readable via .get() or isinstance: {ev!r}")

if failures:
    print("FAILURES:")
    for f in failures:
        print(" -", f)
    sys.exit(1)

print("ALL CRITERIA PASS")
sys.exit(0)
