import logging

logging.disable(logging.CRITICAL)
from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine


def run(target, label):
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
                                        "guard": {"type": "stateIn", "params": {"state": target}},
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
    fired = "m.p.B.b2" in ids
    print(f"{label:46} target={target!r:24} fired={fired}")
    return fired


def main() -> int:
    run("#m.p.A.left.work", "fully-qualified inactive branch (want False)")
    run("#m.p.A.right.work", "fully-qualified active branch (want True)")
    run("left.work", "relative path of the INACTIVE branch (want False)")
    run("right.work", "relative path of the ACTIVE branch (want True)")

    print(
        "\nEXPECTED: a bare, ambiguous state name ('work', matching both "
        "m.p.A.left.work and m.p.A.right.work) is REJECTED (at build time or "
        "at guard-evaluation time), not silently resolved to whichever branch "
        "happens to be active."
    )
    try:
        fired = run("work", "ambiguous bare leaf name (2 states named work)")
        print(
            "OBSERVED: no exception raised; 'stateIn' silently resolved the "
            f"ambiguous name (fired={fired})."
        )
        ok = False
    except Exception as exc:  # noqa: BLE001
        print(f"OBSERVED: raised {type(exc).__name__}: {exc}")
        ok = True
    print("RESULT:", "PASS" if ok else "FAIL (ambiguous bare name resolved silently, not rejected)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
