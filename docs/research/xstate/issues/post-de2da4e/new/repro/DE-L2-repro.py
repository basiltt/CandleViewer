"""DE-L2 repro: an inline-dict `invoke.src` fails with an opaque
`TypeError: unhashable type: 'dict'` from deep inside `logic_loader`,
instead of a named `InvalidConfigError` from the #220 validator.

STANDALONE: stdlib + xstate_statemachine only. Run from cwd C:/Users/basil.
"""

import sys

sys.path.insert(
    0,
    "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/"
    "xstate-statemachine/src",
)
from xstate_statemachine import create_machine, MachineLogic  # noqa: E402

# An inline nested-machine config dict supplied directly as `invoke.src`.
# NOTE: there is no typo anywhere in this config -- it is well-formed.
CLEAN = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {
            "invoke": {
                "id": "kid",
                "src": {
                    "id": "kid",
                    "initial": "k",
                    "states": {"k": {}},
                },
            }
        }
    },
}

# The same shape, with a typo (`entyr` for `entry`) inside the sub-machine.
TYPO = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {
            "invoke": {
                "id": "kid",
                "src": {
                    "id": "kid",
                    "initial": "k",
                    "states": {"k": {"entyr": ["nope"]}},
                },
            }
        }
    },
}

# Control: the identical typo one level up, as an ordinary state config.
CONTROL = {"id": "m2", "initial": "a", "states": {"a": {"entyr": ["nope"]}}}


def attempt(label, cfg, strict):
    try:
        create_machine(cfg, logic=MachineLogic(), strict_config=strict)
        return f"{label:28s} strict={strict!s:5s} -> built OK"
    except Exception as exc:  # noqa: BLE001 -- the point is which type
        return (
            f"{label:28s} strict={strict!s:5s} -> "
            f"{type(exc).__name__}: {str(exc)[:60]}"
        )


lines = [
    attempt("inline dict src, no typo", CLEAN, False),
    attempt("inline dict src, no typo", CLEAN, True),
    attempt("inline dict src, with typo", TYPO, True),
    attempt("control: typo one level up", CONTROL, True),
]
for line in lines:
    print(line)

opaque = "TypeError" in lines[0] and "TypeError" in lines[1]
named_control = "InvalidConfigError" in lines[3]
print()
print("a well-formed inline-dict src fails with TypeError :", opaque)
print("the same typo one level up is named properly       :", named_control)
print()
print("REPRODUCED:", opaque and named_control)
sys.exit(1 if (opaque and named_control) else 0)
