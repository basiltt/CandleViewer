"""Verify #132: an ambiguous bare stateIn name is REJECTED (InvalidConfigError)
rather than silently resolved; fully-qualified and unambiguous relative
spellings continue to work unchanged.
"""
import sys

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.exceptions import InvalidConfigError

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


def run(target):
    CFG = {
        "id": "m",
        "initial": "p",
        "states": {
            "p": {
                "type": "parallel",
                "states": {
                    "A": {
                        "initial": "right",
                        "states": {
                            "left": {"initial": "work", "states": {"work": {}}},
                            "right": {"initial": "work", "states": {"work": {}}},
                        },
                    },
                    "B": {
                        "initial": "b1",
                        "states": {
                            "b1": {
                                "on": {
                                    "E": {
                                        "target": "b2",
                                        "guard": {
                                            "type": "stateIn",
                                            "params": {"state": target},
                                        },
                                    }
                                }
                            },
                            "b2": {},
                        },
                    },
                },
            }
        },
    }
    s = SyncInterpreter(create_machine(CFG, logic=MachineLogic())).start()
    s.send("E")
    ids = sorted(s.current_state_ids)
    s.stop()
    return "m.p.B.b2" in ids


def main() -> int:
    check(
        "criterion 2: fully-qualified inactive branch -> False",
        run("#m.p.A.left.work") is False,
    )
    check(
        "criterion 2: fully-qualified active branch -> True",
        run("#m.p.A.right.work") is True,
    )
    check(
        "criterion 2: relative inactive -> False",
        run("left.work") is False,
    )
    check(
        "criterion 2: relative active -> True",
        run("right.work") is True,
    )

    raised = None
    try:
        run("work")
    except InvalidConfigError as exc:
        raised = exc
    except Exception as exc:  # noqa: BLE001
        raised = exc
    print("ambiguous bare name raised:", type(raised).__name__, raised)
    check(
        "criterion 1: ambiguous bare name raises InvalidConfigError",
        isinstance(raised, InvalidConfigError),
    )

    ok = all(c for _, c in results)
    print("OVERALL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
