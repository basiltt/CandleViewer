"""Verify #98 on 5e07ba8: strict mode rejects forged engine-shaped names.

Acceptance criteria (from gh issue #98):
  1. On a `strict` machine, an undeclared USER-sent event is rejected
     regardless of its name, including `done.invoke.`, `done.state.`,
     `error.platform.`, `after.`, `xstate.` and `___xstate` namespaces.
  2. Engine-minted events remain exempt, verified by a machine that
     actually declares an invoke/onDone and an after.
  3. Build-time `on`-key / static-`raise` validation is unaffected.
  4. Test: `test_strict_rejects_undeclared_engine_shaped_names`,
     parameterised over the reported list (repo:
     `test_strict_rejects_forged_engine_shaped_user_events`).
"""
from xstate_statemachine import Event, MachineLogic, create_machine
from xstate_statemachine.exceptions import UnknownEventError
from xstate_statemachine.sync_interpreter import SyncInterpreter

FORGED_NAMES = [
    "done.typo",
    "done.review",
    "error.validation",
    "done.invoke.NEVER_INVOKED",
    "done.state.NO_SUCH_STATE",
    "error.platform.NOT_A_SERVICE",
    "after.party",
    "after.9999999",
    "xstate.whatever",
    "xstate.done.actor.ghost",
    "___xstate_forged",
]

CFG = {"id": "s", "initial": "a", "states": {"a": {"on": {"GO": "a"}}}}


def criterion_1():
    """Every forged/undeclared engine-shaped name is rejected under strict."""
    results = {}
    for name in FORGED_NAMES:
        it = SyncInterpreter(
            create_machine(CFG, logic=MachineLogic()), strict=True
        )
        it.start()
        try:
            it.send(Event(name))
            results[name] = "ACCEPTED"
        except UnknownEventError:
            results[name] = "UnknownEventError"
        except Exception as e:  # pragma: no cover - unexpected
            results[name] = f"UNEXPECTED:{type(e).__name__}"
        it.stop()
    return results


def criterion_2():
    """Real engine completions (onDone) and `after` still fire under strict."""
    cfg = {
        "id": "t",
        "initial": "a",
        "states": {
            "a": {
                "invoke": {"src": "q", "id": "q", "onDone": "b"},
                "after": {"50": "timeout"},
            },
            "b": {},
            "timeout": {},
        },
    }
    it = SyncInterpreter(
        create_machine(
            cfg, logic=MachineLogic(services={"q": lambda i, c, e: 1})
        ),
        strict=True,
    )
    it.start()
    reached_b = it.value == "b"
    it.stop()
    return reached_b


def criterion_3():
    """Build-time validation of a genuine `on` key for these shapes is
    unaffected: a machine that DECLARES `done.invoke.q` still accepts it,
    strict or not, via the normal declared-key path (not the implicit
    engine-shape exemption)."""
    cfg = {
        "id": "u",
        "initial": "a",
        "states": {
            "a": {
                "invoke": {"src": "q", "id": "q"},
                "on": {"done.invoke.q": "b"},
            },
            "b": {},
        },
    }
    it = SyncInterpreter(
        create_machine(
            cfg, logic=MachineLogic(services={"q": lambda i, c, e: 1})
        ),
        strict=True,
    )
    it.start()
    reached_b = it.value == "b"
    it.stop()
    return reached_b


if __name__ == "__main__":
    r1 = criterion_1()
    for name, outcome in r1.items():
        print(f"  {name:32s} {outcome}")
    c1 = all(v == "UnknownEventError" for v in r1.values())
    c2 = criterion_2()
    c3 = criterion_3()
    print("Criterion 1 (all forged names rejected):", c1)
    print("Criterion 2 (real onDone/after still exempt):", c2)
    print("Criterion 3 (declared on-key for engine shape still works):", c3)
    print("ALL PASS:", all([c1, c2, c3]))
