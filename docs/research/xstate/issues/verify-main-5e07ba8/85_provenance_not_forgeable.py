"""Verify #85 on main@5e07ba8: Event(system=True) forgery is closed.

Acceptance criteria (from `gh issue view 85`):
1. A user-constructed Event is subject to strict / event_schemas /
   onUnhandled / "*" regardless of any `system` value the caller sets.
2. Engine-minted events remain exempt.
3. Both engines behave identically.
4. test_user_cannot_forge_system_event equivalent, covering "*", strict,
   event_schemas and onUnhandled, on both engines and via send_threadsafe.
5. Event.system (or its replacement) is documented or private.

Also probes the CHANGELOG's specific claim: the sentinel must not be
reachable via copy/replace/pickle/__dict__/dataclasses.replace.
"""
import asyncio
import copy
import dataclasses
import pickle
import sys
import threading
import time
import traceback

from xstate_statemachine import Event, MachineLogic, create_machine
from xstate_statemachine.events import is_system_event, system_event
from xstate_statemachine.interpreter import Interpreter
from xstate_statemachine.sync_interpreter import SyncInterpreter
from xstate_statemachine.exceptions import UnknownEventError

FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {detail}")
    if not cond:
        FAILURES.append(name)


STAR = {
    "id": "s", "initial": "a",
    "states": {"a": {"on": {"*": {"target": "b"}}}, "b": {}},
}
STRICT = {
    "id": "t", "initial": "a",
    "states": {"a": {"on": {"GO": {"target": "b"}}}, "b": {}},
}
UNH = {
    "id": "u", "initial": "a", "onUnhandled": "error",
    "states": {"a": {"on": {"GO": {"target": "b"}}}, "b": {}},
}


def try_forge_constructor():
    try:
        Event("X", system=True)  # type: ignore[call-arg]
        return None
    except TypeError as e:
        return e


def try_forge_via_object():
    """AC1 constructor path: TypeError expected."""
    return try_forge_constructor()


async def async_checks():
    # 1. Constructor has no `system` kwarg (criterion 1/5).
    exc = try_forge_constructor()
    check("AC1/5: Event(system=True) raises TypeError", isinstance(exc, TypeError), repr(exc))

    # 2. `system` property is read-only.
    e = Event("X")
    try:
        e.system = True  # type: ignore[misc]
        ro = False
    except Exception:
        ro = True
    check("AC5: Event.system is read-only", ro)

    # 3. Sentinel not reachable via copy / dataclasses.replace / pickle / __dict__.
    plain = Event("NOT_DECLARED")
    engine_ev = system_event("xstate.error.actor.kid", error="x")

    cp = copy.copy(plain)
    dcp = copy.deepcopy(plain)
    check("copy.copy(user event) stays non-system", not is_system_event(cp))
    check("copy.deepcopy(user event) stays non-system", not is_system_event(dcp))

    # dataclasses.replace should not let a user flip provenance (no public field to set).
    try:
        forged = dataclasses.replace(plain, type="FORGED")
        check(
            "dataclasses.replace cannot forge provenance",
            not is_system_event(forged),
        )
    except Exception as ex:
        check("dataclasses.replace path handled (exception acceptable)", True, repr(ex))

    # Attempt to replace an engine-minted event's type; provenance should carry
    # (replace copies all fields incl. private ones set via init=False? Actually
    # init=False fields are NOT passed to __init__ by replace, so this checks
    # whether replace silently drops or preserves provenance -- either is fine
    # as long as a PLAIN user object never becomes "system" from nothing.)
    try:
        replaced_engine = dataclasses.replace(engine_ev, type="STILL")
        note = f"provenance after replace(engine_event)={is_system_event(replaced_engine)}"
    except Exception as ex:
        note = f"replace(engine_event) raised {ex!r}"
    print(f"[INFO] {note}")

    # pickle round-trip of a plain event must not become system.
    pk = pickle.loads(pickle.dumps(plain))
    check("pickle round-trip of user event stays non-system", not is_system_event(pk))

    # Attempt to forge via __dict__ / object.__setattr__ with a bool (not the
    # real sentinel object) -- must NOT be treated as system since the check
    # is identity-based against an unexported object.
    forged2 = Event("NOT_DECLARED")
    object.__setattr__(forged2, "_provenance", True)
    check(
        "object.__setattr__(_provenance, True) does not forge (identity check)",
        not is_system_event(forged2),
    )
    # Even setting it to some arbitrary truthy sentinel object doesn't help
    # since attacker doesn't have the real `_ENGINE_MARK` object identity.
    forged3 = Event("NOT_DECLARED")
    object.__setattr__(forged3, "_provenance", object())
    check(
        "object.__setattr__(_provenance, <other object>) does not forge",
        not is_system_event(forged3),
    )

    # 4. Behavioural checks across "*", strict, onUnhandled -- async engine.
    it = await Interpreter(create_machine(STAR, logic=MachineLogic())).start()
    await it.send(Event("ANYTHING"))
    await asyncio.sleep(0.05)
    star_plain = set(it.current_state_ids)
    await it.stop()
    check('AC1 async "*" matches plain user event', star_plain == {"s.b"}, star_plain)

    it2 = await Interpreter(
        create_machine(STRICT, logic=MachineLogic()), strict=True
    ).start()
    try:
        await it2.send(Event("NOT_DECLARED"))
        strict_plain_ok = False
    except UnknownEventError:
        strict_plain_ok = True
    await it2.stop()
    check("AC1 async strict rejects plain undeclared event", strict_plain_ok)

    it3 = await Interpreter(create_machine(UNH, logic=MachineLogic())).start()
    await it3.send(Event("NOPE"))
    await asyncio.sleep(0.05)
    unh_plain_status = it3.status
    await it3.stop()
    check(
        "AC1 async onUnhandled=error trips on plain unknown event",
        unh_plain_status == "error",
        unh_plain_status,
    )

    # Engine-minted events remain exempt (criterion 2).
    it4 = await Interpreter(create_machine(UNH, logic=MachineLogic())).start()
    it4._put_inbox(system_event("xstate.whatever"))
    await asyncio.sleep(0.05)
    unh_system_status = it4.status
    await it4.stop()
    check(
        "AC2 async engine-minted event exempt from onUnhandled=error",
        unh_system_status == "running",
        unh_system_status,
    )


def sync_checks():
    it = SyncInterpreter(create_machine(STAR, logic=MachineLogic()))
    it.start()
    it.send(Event("ANYTHING"))
    star_plain = set(it.current_state_ids)
    it.stop()
    check('AC1/3 sync "*" matches plain user event', star_plain == {"s.b"}, star_plain)

    it2 = SyncInterpreter(create_machine(STRICT, logic=MachineLogic()), strict=True)
    it2.start()
    try:
        it2.send(Event("NOT_DECLARED"))
        strict_plain_ok = False
    except UnknownEventError:
        strict_plain_ok = True
    it2.stop()
    check("AC1/3 sync strict rejects plain undeclared event", strict_plain_ok)

    it3 = SyncInterpreter(create_machine(UNH, logic=MachineLogic()))
    it3.start()
    it3.send(Event("NOPE"))
    unh_plain_status = it3.status
    it3.stop()
    check(
        "AC1/3 sync onUnhandled=error trips on plain unknown event",
        unh_plain_status == "error",
        unh_plain_status,
    )


def threadsafe_checks():
    async def runner():
        it = await Interpreter(create_machine(STAR, logic=MachineLogic())).start()
        loop = asyncio.get_running_loop()

        def from_thread():
            it.send_threadsafe(Event("ANYTHING"))

        th = threading.Thread(target=from_thread)
        th.start()
        th.join()
        await asyncio.sleep(0.1)
        result = set(it.current_state_ids)
        await it.stop()
        return result

    result = asyncio.run(runner())
    check('AC4 send_threadsafe: "*" matches plain user event', result == {"s.b"}, result)


def main():
    asyncio.run(async_checks())
    sync_checks()
    threadsafe_checks()
    print()
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("RESULT: ALL PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
