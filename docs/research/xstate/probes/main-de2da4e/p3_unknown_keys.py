"""P3 (#220): recursive unknown-key check -- false-positive surface.

STANDALONE except that part 1 walks a directory of *.machine.json if one
is given on the command line (optional). Part 2 is self-contained.
"""
import glob
import json
import os
import sys

from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.exceptions import InvalidConfigError
from xstate_statemachine.validation import (
    KNOWN_INVOKE_KEYS,
    KNOWN_ROOT_KEYS,
    KNOWN_STATE_KEYS,
    KNOWN_TRANSITION_KEYS,
    validate_top_level_keys,
)


def corpus(dirs):
    bad = 0
    total = 0
    for d in dirs:
        for path in glob.glob(os.path.join(d, "*.machine.json")):
            total += 1
            with open(path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            try:
                validate_top_level_keys(cfg, strict_config=True)
            except InvalidConfigError as exc:
                bad += 1
                print(f"  REJECTED {os.path.basename(path)}\n    {exc}")
    print(f"corpus: {total} charts, {bad} rejected under strict_config")


CASES = {
    # (name, config, expect_clean)
    "nested typo caught": (
        {
            "id": "m",
            "initial": "a",
            "states": {"a": {"entyr": [], "onn": {}}},
        },
        False,
    ),
    "x- accepted at every level": (
        {
            "id": "m",
            "x-doc": 1,
            "initial": "a",
            "states": {
                "a": {
                    "x-ui": 1,
                    "on": {"E": {"target": "a", "x-note": 1}},
                    "invoke": {"src": "s", "x-tag": 1},
                }
            },
        },
        True,
    ),
    "meta/description/tags everywhere": (
        {
            "id": "m",
            "description": "d",
            "initial": "a",
            "states": {
                "a": {
                    "meta": {},
                    "tags": ["t"],
                    "on": {"E": {"target": "a", "meta": {}}},
                }
            },
        },
        True,
    ),
    "history state": (
        {
            "id": "m",
            "initial": "p",
            "states": {
                "p": {
                    "initial": "a",
                    "states": {
                        "a": {},
                        "h": {"type": "history", "history": "deep", "target": "a"},
                    },
                }
            },
        },
        True,
    ),
    "invoke src = inline machine dict (child states not walked?)": (
        {
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
        },
        True,  # documents CURRENT behaviour: typo inside inline src ignored
    ),
    "transition list form": (
        {
            "id": "m",
            "initial": "a",
            "states": {
                "a": {
                    "on": {
                        "E": [
                            {"target": "a", "guard": "g"},
                            {"target": "a", "cond": "g2"},
                        ]
                    }
                }
            },
        },
        True,
    ),
    "root policies under a state are flagged": (
        {
            "id": "m",
            "initial": "a",
            "states": {"a": {"maxIterations": 5}},
        },
        False,
    ),
    "parallel regions": (
        {
            "id": "m",
            "type": "parallel",
            "states": {
                "r1": {"initial": "a", "states": {"a": {}}},
                "r2": {"initial": "b", "states": {"b": {"tpye": "final"}}},
            },
        },
        False,
    ),
    "always list + after": (
        {
            "id": "m",
            "initial": "a",
            "states": {
                "a": {
                    "always": [{"target": "b", "guard": "g"}],
                    "after": {"100": {"target": "b", "actions": []}},
                },
                "b": {},
            },
        },
        True,
    ),
    "onDone on compound + invoke onError": (
        {
            "id": "m",
            "initial": "a",
            "states": {
                "a": {
                    "initial": "i",
                    "states": {"i": {"type": "final"}},
                    "onDone": {"target": "b"},
                    "invoke": {
                        "src": "s",
                        "onDone": {"target": "b"},
                        "onError": {"target": "b"},
                    },
                },
                "b": {},
            },
        },
        True,
    ),
    "final state 'output'": (
        {
            "id": "m",
            "initial": "a",
            "states": {"a": {"type": "final", "output": {"k": 1}}},
        },
        True,
    ),
}


def cases():
    for name, (cfg, expect_clean) in CASES.items():
        try:
            validate_top_level_keys(cfg, strict_config=True)
            got = "clean"
            err = ""
        except InvalidConfigError as exc:
            got = "REJECTED"
            err = str(exc).split("--", 1)[-1].strip()[:150]
        flag = "ok " if (got == "clean") == expect_clean else "!! "
        print(f"{flag}{name}: {got} {err}")


def main():
    print("ROOT-only keys:", sorted(KNOWN_ROOT_KEYS - KNOWN_STATE_KEYS))
    print("STATE keys:", sorted(KNOWN_STATE_KEYS))
    print("TRANSITION keys:", sorted(KNOWN_TRANSITION_KEYS))
    print("INVOKE keys:", sorted(KNOWN_INVOKE_KEYS))
    print("--- synthetic cases (expect flag 'ok') ---")
    cases()
    if len(sys.argv) > 1:
        print("--- corpus ---")
        corpus(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
