"""Verify #188: SyncInterpreter._deferred_this_step is cleared on every
step, not only the wait=True path."""
from xstate_statemachine import create_machine, SyncInterpreter

CFG = {
    "id": "m",
    "initial": "a",
    "context": {},
    "onUnhandled": "defer",
    "states": {"a": {}},
}


def main():
    machine = create_machine(CFG, logic=None)
    interp = SyncInterpreter(machine)
    interp.start()

    N = 5000
    for i in range(N):
        interp.send(f"EV_{i}", wait=False)

    leaked_after_fire_and_forget = len(interp._deferred_this_step)

    interp.send("EV_FINAL", wait=True)
    leaked_after_wait_true = len(interp._deferred_this_step)

    cells = {
        "SyncInterpreter/fire-and-forget(wait=False)x5000": leaked_after_fire_and_forget,
        "SyncInterpreter/after one wait=True send": leaked_after_wait_true,
    }
    print("cell table:")
    for k, v in cells.items():
        print(f"  {k}: {v}")

    # Fixed behaviour: per-step scope holds at most the events deferred in
    # the LAST processed step (<=1 here, since each send is its own step and
    # the previous step's deferral is cleared at the start of the next step).
    ok = leaked_after_fire_and_forget <= 1 and leaked_after_wait_true <= 1
    print("ALL PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
