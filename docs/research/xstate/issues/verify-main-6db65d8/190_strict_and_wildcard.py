"""Verify #190: config-level "strict": true rejects undeclared event names,
and a "*" handler does not defeat strict / is_known_event()."""
import asyncio
from xstate_statemachine import (
    create_machine,
    Interpreter,
    SyncInterpreter,
)
from xstate_statemachine.exceptions import UnknownEventError


def cfg_strict_no_wildcard():
    return {
        "id": "p1",
        "initial": "a",
        "strict": True,
        "context": {},
        "states": {"a": {"on": {"KNOWN": "a"}}},
    }


def cfg_wildcard():
    return {
        "id": "p2",
        "initial": "a",
        "context": {},
        "states": {"a": {"on": {"KNOWN": "a", "*": {"actions": []}}}},
    }


def part1_strict_inherited(interp_cls, is_async):
    machine = create_machine(cfg_strict_no_wildcard(), logic=None)
    interp = interp_cls(machine)  # no explicit strict kwarg -> inherit machine.strict
    if is_async:
        async def go():
            await interp.start()
            try:
                await interp.send("TOTALLY_UNDECLARED", wait=True)
                return False
            except UnknownEventError:
                return True
        return asyncio.run(go())
    else:
        interp.start()
        try:
            interp.send("TOTALLY_UNDECLARED", wait=True)
            return False
        except UnknownEventError:
            return True


def part2_wildcard_does_not_defeat_strict(interp_cls, is_async):
    machine = create_machine(cfg_wildcard(), logic=None)
    known = machine.is_known_event("TOTALLY_UNDECLARED", user_sent=True)
    interp = interp_cls(machine, strict=True)
    if is_async:
        async def go():
            await interp.start()
            try:
                await interp.send("TOTALLY_UNDECLARED", wait=True)
                return False
            except UnknownEventError:
                return True
        rejected = asyncio.run(go())
    else:
        interp.start()
        try:
            interp.send("TOTALLY_UNDECLARED", wait=True)
            rejected = False
        except UnknownEventError:
            rejected = True
    return (not known) and rejected


def main():
    cells = {}
    cells["SyncInterpreter/part1-strict-inherited"] = part1_strict_inherited(SyncInterpreter, False)
    cells["Interpreter/part1-strict-inherited"] = part1_strict_inherited(Interpreter, True)
    cells["SyncInterpreter/part2-wildcard-vs-strict"] = part2_wildcard_does_not_defeat_strict(SyncInterpreter, False)
    cells["Interpreter/part2-wildcard-vs-strict"] = part2_wildcard_does_not_defeat_strict(Interpreter, True)

    print("cell table:")
    for k, v in cells.items():
        print(f"  {k}: {v}")

    ok = all(cells.values())
    print("ALL PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
