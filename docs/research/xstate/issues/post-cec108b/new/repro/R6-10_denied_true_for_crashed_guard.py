"""R6-10: Receipt.denied is True for a guard that CRASHED under
guardErrorPolicy="raise", not just for a guard that returned False.

`_is_guard_satisfied` returns False on the raise path (base_interpreter.py
~4834), and the transition-selection loop treats "returned False" and
"crashed" identically: both set `_guard_denied_this_step = True`
(base_interpreter.py ~4314). The resulting Receipt.denied is therefore True
for two semantically different cases, though `Receipt.error` still
discriminates them (this script prints both).

Run: python R6-10_denied_true_for_crashed_guard.py
Expect (bug present): case "crash" -> denied=True, error is not None
Expect (fixed):        case "crash" -> denied=False (or documented discriminator)
"""
import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine


CFG_FALSE = {
    "id": "g_false",
    "initial": "a",
    "guardErrorPolicy": "raise",
    "states": {
        "a": {"on": {"GO": {"target": "b", "guard": "nope"}}},
        "b": {"type": "final"},
    },
}

CFG_CRASH = {
    "id": "g_crash",
    "initial": "a",
    "guardErrorPolicy": "raise",
    "states": {
        "a": {"on": {"GO": {"target": "b", "guard": "boom"}}},
        "b": {"type": "final"},
    },
}


def guard_false(ctx, event):
    return False


def guard_boom(ctx, event):
    raise RuntimeError("guard crashed")


async def run_case(cfg, guards, label):
    # NOTE: MachineLogic wants callables, not a bare class; this cost us
    # a debugging pass before we noticed the harness error.
    m = create_machine(cfg, logic=MachineLogic(guards=guards))
    i = Interpreter(m)
    await i.start()
    # NOTE: sync send() needs wait=True to get a Receipt back at all.
    receipt = await i.send("GO", wait=True)
    print(
        f"case={label:5s} denied={receipt.denied!s:5s} "
        f"deferred={receipt.deferred!s:5s} "
        f"error={type(receipt.error).__name__ if receipt.error else None} "
        f"changed={receipt.changed}"
    )
    await i.stop()
    return receipt


async def main():
    false_receipt = await run_case(CFG_FALSE, {"nope": guard_false}, "false")
    crash_receipt = await run_case(CFG_CRASH, {"boom": guard_boom}, "crash")

    # Bug assertion: a crashed guard should not be labelled the same as a
    # guard that merely returned False -- but `denied` conflates them while
    # `error` is populated only for the crash.
    bug_present = (
        false_receipt.denied is True
        and crash_receipt.denied is True
        and crash_receipt.error is not None
    )
    if bug_present:
        print(
            "BUG CONFIRMED: denied=True for both a refused guard and a "
            "crashed guard; only `error is not None` discriminates them."
        )
        sys.exit(1)
    else:
        print("Not reproduced: denied no longer conflates the two cases.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
