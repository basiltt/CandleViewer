# -*- coding: utf-8 -*-
"""R7-13 -- two related gaps in event-name strictness:

1. Config-level `"strict": true` (`MachineNode.strict`, set from
   `config.get("strict", False)`) does NOT gate event names by itself --
   only `Interpreter(strict=True)` (an explicit interpreter-construction
   argument) does. `_check_strict` (`base_interpreter.py`) reads
   `self.strict`, which is `machine.strict if strict is None else
   bool(strict)` -- so passing nothing to the interpreter should inherit the
   machine's `strict` flag, yet an undeclared event name still sails
   through when the interpreter isn't told `strict=True` explicitly.
2. A bare `"*"` handler anywhere in the chart makes `MachineNode.
   is_known_event()` return `True` for EVERY event type (`models.py`,
   `is_known_event`: `if "*" in known or event_type in known: return True`),
   so any conformance check -- including `strict` itself, once armed --
   built on that predicate is silently vacuous.

Library only, no project machinery. main @ 221ce7c (unreleased 0.8.1;
`__version__` still reports 0.8.0 -- key on the commit). Python 3.13.

Exit code 1 == either gap reproduced (config-level strict alone accepted an
undeclared name, or a wildcard handler made an explicit `strict=True`
interpreter accept one too). Exit code 0 == both gated correctly.
"""
import asyncio

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import UnknownEventError

# --- Part 1: config-level `strict: true` alone --------------------------
CFG_STRICT_NO_WILDCARD = {
    "id": "p1",
    "strict": True,
    "initial": "a",
    "context": {},
    "states": {"a": {"on": {"KNOWN": {}}}},
}

# --- Part 2: explicit interpreter strict=True, but a "*" handler present -
CFG_WILDCARD = {
    "id": "p2",
    "initial": "a",
    "context": {},
    "states": {"a": {"on": {"KNOWN": {}, "*": {"actions": []}}}},
}


async def part1_config_strict_alone() -> bool:
    """Returns True if the gap reproduced (undeclared name ACCEPTED)."""
    m = create_machine(CFG_STRICT_NO_WILDCARD, logic=MachineLogic())
    print("machine.strict = %r" % (m.strict,))
    it = Interpreter(m)  # no explicit strict= kwarg -> should inherit machine.strict
    await it.start()
    try:
        await it.send("TOTALLY_UNDECLARED", wait=True)
        print("part1: TOTALLY_UNDECLARED ACCEPTED, running=%s, last_error=%r"
              % (it.is_running, it.last_error))
        gap = True
    except UnknownEventError as exc:
        print("part1: TOTALLY_UNDECLARED -> UnknownEventError: %s" % exc)
        gap = False
    await it.stop()
    return gap


async def part2_wildcard_defeats_strict() -> bool:
    """Returns True if the gap reproduced (is_known_event() lied for a
    wildcard chart, and an explicit strict=True interpreter ACCEPTED an
    undeclared name)."""
    m = create_machine(CFG_WILDCARD, logic=MachineLogic())
    known_says_yes = m.is_known_event("TOTALLY_UNDECLARED", user_sent=True)
    print("part2: is_known_event('TOTALLY_UNDECLARED') with a '*' handler "
          "present = %r (known_events=%r)" % (known_says_yes, sorted(m.known_events)))

    it = Interpreter(m, strict=True)  # explicit strict this time
    await it.start()
    try:
        await it.send("TOTALLY_UNDECLARED", wait=True)
        print("part2: TOTALLY_UNDECLARED ACCEPTED under explicit strict=True, "
              "running=%s" % it.is_running)
        gap = True
    except UnknownEventError as exc:
        print("part2: TOTALLY_UNDECLARED -> UnknownEventError: %s" % exc)
        gap = False
    await it.stop()
    return gap or known_says_yes


async def main() -> int:
    gap1 = await part1_config_strict_alone()
    gap2 = await part2_wildcard_defeats_strict()
    if gap1 or gap2:
        if gap1:
            print("REPRODUCED (1): config-level `strict: true` in the machine "
                  "JSON did not gate event names -- an undeclared event was "
                  "accepted by an interpreter constructed with no explicit "
                  "`strict=` kwarg.")
        if gap2:
            print("REPRODUCED (2): a bare '*' handler makes is_known_event() "
                  "return True for an undeclared name, defeating strict "
                  "enforcement even with an explicit Interpreter(strict=True).")
        print("EXPECTED  : config-level `strict` should gate event names (or "
              "the behaviour should be documented as a no-op); and a wildcard "
              "handler should not make is_known_event() answer 'known' for "
              "an otherwise-undeclared name.")
        return 1
    print("NOT reproduced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
