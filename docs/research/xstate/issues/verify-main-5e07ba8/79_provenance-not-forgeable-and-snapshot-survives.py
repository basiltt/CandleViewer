"""Verify issue #79 (N-8) on main @ 5e07ba8.

Prior disposition (post-3c527b0/79.md): criteria 1-7 fixed; criterion 8
("provenance must not be settable by user code, and must survive a
snapshot") was the reopened residual. CHANGELOG [Unreleased] claims:
`Event(system=True)` has no such public constructor parameter,
`Event.system` is a read-only property backed by an engine-private
identity sentinel that only `system_event()` can set, and provenance
round-trips through get_persisted_snapshot()/from_snapshot() (v2 layout,
#86/#87).
"""

import asyncio
import json
import sys

from xstate_statemachine import (
    Event,
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    UnknownEventError,
    create_machine,
)
from xstate_statemachine.events import is_system_event, system_event


# --- Criteria 1-7 (already fixed at 3c527b0; re-checked for regressions) ---
CFG_WILDCARD = {
    "id": "wc",
    "initial": "a",
    "context": {"caught": []},
    "states": {"a": {"on": {"*": {"actions": ["note"]}}}},
}


def note(i, ctx, event, action):
    ctx["caught"].append(event.type)


async def crits_1_to_6() -> dict:
    i = await Interpreter(
        create_machine(CFG_WILDCARD, logic=MachineLogic(actions={"note": note}))
    ).start()
    for ev in ("PLAIN", "error.myapp.validation", "done.review", "my.namespaced"):
        await i.send(ev)
    await asyncio.sleep(0.05)
    caught = list(i.context["caught"])
    await i.stop()
    return {"caught": caught}


# --- Criterion 8a: provenance is not settable via the public constructor --
def crit8a_no_public_param() -> bool:
    try:
        Event("X", system=True)  # type: ignore[call-arg]
        return False
    except TypeError:
        return True


def crit8b_readonly_property() -> bool:
    e = Event("X")
    if e.system:
        return False
    try:
        e.system = True  # type: ignore[misc]
        return False
    except Exception:
        return True


def crit8c_private_slot_forgery_fails() -> bool:
    """Even reaching under the hood with object.__setattr__ on a plain bool
    must not forge system status (identity sentinel, not a bool)."""
    e = Event("NOT_DECLARED")
    object.__setattr__(e, "_provenance", True)
    if is_system_event(e):
        return False
    cfg = {
        "id": "t",
        "initial": "a",
        "states": {"a": {"on": {"GO": "b"}}, "b": {}},
    }
    i = SyncInterpreter(create_machine(cfg), strict=True)
    i.start()
    try:
        i.send(e)
        ok = False
    except UnknownEventError:
        ok = True
    i.stop()
    return ok


def crit8d_engine_minted_is_system() -> bool:
    e = system_event("___xstate_statemachine_init___")
    return e.system and is_system_event(e)


# --- Criterion 8e: provenance survives get_persisted_snapshot/from_snapshot
CFG_UNH = {
    "id": "u",
    "initial": "a",
    "onUnhandled": "error",
    "states": {"a": {"on": {"GO": "b"}}, "b": {}},
}


async def crit8e_provenance_survives_snapshot() -> str:
    """A restored engine Event (e.g. an error.platform.* system event) must
    not be treated as user traffic by onUnhandled: 'error' after restore."""
    it = await Interpreter(create_machine(CFG_UNH)).start()
    it._put_inbox(system_event("xstate.error.actor.kid", error="x"))
    snap = json.dumps(it.get_persisted_snapshot())
    await it.stop()
    it2 = Interpreter.from_snapshot(snap, create_machine(CFG_UNH))
    await it2.start()
    await asyncio.sleep(0.05)
    st = it2.status
    await it2.stop()
    return st


def main() -> int:
    caught = asyncio.run(crits_1_to_6())["caught"]
    a = crit8a_no_public_param()
    b = crit8b_readonly_property()
    c = crit8c_private_slot_forgery_fails()
    d = crit8d_engine_minted_is_system()
    status = asyncio.run(crit8e_provenance_survives_snapshot())

    print("Criteria 1-6 (* / onUnhandled by provenance):", caught)
    print("Criterion 8a (no public `system=` param):", a)
    print("Criterion 8b (`.system` read-only):", b)
    print("Criterion 8c (slot-forgery still rejected under strict):", c)
    print("Criterion 8d (engine-minted event is system):", d)
    print("Criterion 8e (provenance survives snapshot, status):", status)

    ok = (
        caught == ["PLAIN", "error.myapp.validation", "done.review", "my.namespaced"]
        and a and b and c and d
        and status == "running"
    )
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
