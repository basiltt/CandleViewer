"""K-3 probes: actionErrorPolicy 'fail' -> stopped. Restart, restore,
snapshot round-trip, error typing.
"""
import json

from xstate_statemachine import (
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import (
    InvalidConfigError,
    RestoredError,
    SnapshotCorruptError,
    TransitionFailedError,
)

CFG = {
    "id": "f",
    "initial": "a",
    "actionErrorPolicy": "fail",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"BOOM": {"target": "b", "actions": ["boom"]}}},
        "b": {},
    },
}


def boom(i, c, e, a):
    raise ValueError("kaput")


def build():
    return create_machine(CFG, logic=MachineLogic(actions={"boom": boom}))


def main():
    m = build()
    i = SyncInterpreter(m).start()
    i.send("BOOM")
    print("status:", i.status)
    print("error type:", type(i.error).__name__, "|", i.error)
    print("is TransitionFailedError:", isinstance(i.error, TransitionFailedError))
    print("__cause__:", type(i.error.__cause__).__name__ if i.error else None)
    print("current_state_ids:", i.current_state_ids)

    # restart?
    try:
        i.start()
        print("restart: ALLOWED (bad)")
    except InvalidConfigError as e:
        print("restart: refused InvalidConfigError ok")

    # snapshot of a fail-stopped machine
    try:
        snap = i.get_snapshot()
        d = json.loads(snap)
        print("snapshot status:", d["status"])
        print("snapshot state_ids:", d["state_ids"])
        print("snapshot configuration:", d.get("configuration"))
        print("snapshot error:", d.get("error"))
    except Exception as e:
        print("snapshot raised:", type(e).__name__, e)
        return

    # restore it
    try:
        r = SyncInterpreter.from_snapshot(snap, build())
        print("restore: ok status=", r.status, "ids=", r.current_state_ids)
        print("restore error:", type(r.error).__name__ if r.error else None,
              "|", r.error)
        try:
            r.start()
            print("restored.start(): ALLOWED -> status", r.status)
        except InvalidConfigError:
            print("restored.start(): refused ok")
        print("restored send:", r.send("BOOM"))
    except SnapshotCorruptError as e:
        print("restore: SnapshotCorruptError:", e)
    except Exception as e:
        print("restore:", type(e).__name__, e)


if __name__ == "__main__":
    main()
