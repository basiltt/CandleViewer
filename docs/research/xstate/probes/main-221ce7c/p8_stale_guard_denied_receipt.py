"""L-8 probe: `_guard_denied_this_step` is also reset only under `if wait:`
on the sync engine, so it is STICKY across fire-and-forget sends and
poisons the next receipt.

A guard-denied `send("X")` (wait=False) leaves the flag True. The next
`send("Y", wait=True)` for an event that is simply UNHANDLED (no guard
anywhere) then reports `Receipt.denied is True` -- "a guard returned
False" -- when no guard ran. `denied` is exactly the field #170's
documented `(denied, error is None)` discrimination rests on.
"""

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

CONFIG = {
    "id": "p8",
    "initial": "a",
    "states": {
        "a": {
            "on": {
                "GUARDED": {"target": "b", "guard": "never"},
                # "IGNORED" is not declared anywhere: unhandled, no guard.
            }
        },
        "b": {},
    },
}


def never(ctx, ev):  # noqa: ANN001
    return False


def main() -> None:
    m = create_machine(CONFIG, logic=MachineLogic(guards={"never": never}))

    # Baseline: clean interpreter, no prior denial.
    i = SyncInterpreter(m)
    i.start()
    r = i.send("IGNORED", wait=True)
    print(f"baseline  IGNORED wait=True -> denied={r.denied} error={r.error}")
    i.stop()

    # Poisoned: one fire-and-forget denied send first.
    j = SyncInterpreter(m)
    j.start()
    j.send("GUARDED")  # wait=False -> flag set, never cleared
    print(f"flag after wait=False denied send: {j._guard_denied_this_step}")
    r2 = j.send("IGNORED", wait=True)
    print(f"poisoned  IGNORED wait=True -> denied={r2.denied} error={r2.error}")
    print(
        "VERDICT:",
        "STALE denied=True ON AN EVENT NO GUARD SAW"
        if r2.denied and not r.denied
        else "no leakage",
    )
    j.stop()


main()
