"""Verify issue #31 (LC-07) on main @ 5e07ba8.

Prior disposition (post-3c527b0/31.md): criteria 1,2,3,5 were already
fixed; criterion 4 (both engines agree at runtime under
strict_targets=False) was the reopened residual. CHANGELOG [Unreleased]
claims: "Runtime parity for unresolvable targets under
strict_targets=False (#31): both engines now expose the same surface --
StateNotFoundError on the receipt, last_transition_ok=False, last_error
set, machine still running; the sync engine additionally raises from a
fire-and-forget send() as before." Also a ride-along: _SIBLING_FALLBACKS_WARNED
is bounded to 1024 pairs.
"""

import asyncio
import sys
import warnings

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    StateNotFoundError,
    SyncInterpreter,
    create_machine,
)

# --- Criterion 1: child-first resolution -----------------------------------
CFG_CHILD = {
    "id": "m",
    "initial": "A",
    "states": {
        "A": {
            "initial": "A1",
            "on": {"GO": {"target": ".A2"}},
            "states": {"A1": {"exit": ["xA1"]}, "A2": {"entry": ["eA2"]}},
        }
    },
}


async def crit1() -> bool:
    log = []
    logic = MachineLogic(
        actions={
            n: (lambda i, c, e, a, n=n: log.append(n)) for n in ("xA1", "eA2")
        }
    )
    machine = create_machine(CFG_CHILD, logic=logic)
    interp = await Interpreter(machine).start()
    await interp.send("GO")
    await asyncio.sleep(0.05)
    state = sorted(interp.current_state_ids)
    await interp.stop()
    return state == ["m.A.A2"] and log == ["xA1", "eA2"]


# --- Criterion 2: sibling fallback + DeprecationWarning ---------------------
CFG_SIB = {
    "id": "m2",
    "initial": "A",
    "states": {
        "A": {"on": {"GO": {"target": ".B"}}},
        "B": {},
    },
}


def crit2() -> bool:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        machine = create_machine(CFG_SIB, strict_targets=False)
        warned = any(issubclass(x.category, DeprecationWarning) for x in w)
    i = SyncInterpreter(machine)
    i.start()
    i.send("GO")
    ok = i.value == "B" and warned
    i.stop()
    return ok


# --- Criterion 4 (the reopened one): engine parity for unresolvable target --
CFG_BAD = {
    "id": "m3",
    "initial": "A",
    "states": {"A": {"on": {"GO": {"target": ".zzz"}}}},
}


async def crit4_async() -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        machine = create_machine(CFG_BAD, strict_targets=False)
    i = await Interpreter(machine).start()
    r = await i.send("GO", wait=True)
    await asyncio.sleep(0.02)
    out = {
        "receipt_error": type(r.error).__name__ if r.error else None,
        "last_transition_ok": i.last_transition_ok,
        "last_error": type(i.last_error).__name__ if i.last_error else None,
        "running": i.status == "running",
    }
    await i.stop()
    return out


def crit4_sync() -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        machine = create_machine(CFG_BAD, strict_targets=False)
    i = SyncInterpreter(machine)
    i.start()
    raised = None
    try:
        i.send("GO")
    except StateNotFoundError as exc:
        raised = type(exc).__name__
    out = {
        "raised_fire_and_forget": raised,
        "last_transition_ok": i.last_transition_ok,
        "last_error": type(i.last_error).__name__ if i.last_error else None,
        "running": i.status == "running",
    }
    i.stop()
    return out


def main() -> int:
    ok1 = asyncio.run(crit1())
    ok2 = crit2()
    a = asyncio.run(crit4_async())
    s = crit4_sync()

    print("Criterion 1 (child-first)      :", "PASS" if ok1 else "FAIL")
    print("Criterion 2 (sibling+warning)   :", "PASS" if ok2 else "FAIL")
    print("Criterion 4 async surface       :", a)
    print("Criterion 4 sync surface        :", s)

    parity = (
        a["receipt_error"] == "StateNotFoundError"
        and a["last_transition_ok"] is False
        and a["last_error"] == "StateNotFoundError"
        and a["running"] is True
        and s["raised_fire_and_forget"] == "StateNotFoundError"
        and s["last_transition_ok"] is False
        and s["last_error"] == "StateNotFoundError"
        and s["running"] is True
    )
    print("Criterion 4 (engine parity)    :", "PASS" if parity else "FAIL")

    ok = ok1 and ok2 and parity
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
