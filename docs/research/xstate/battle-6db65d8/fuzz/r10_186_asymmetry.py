"""R10 -- ISOLATE the #186 asymmetry found by r9.A1.

#186's claim: "`configuration or state_ids` let an emptied or rewritten
`configuration` silently win or silently lose; the two must agree or the blob
is refused with SnapshotCorruptError."

r9 found the check is ONE-SIDED:
    configuration={} / [] / bogus / extra   -> refused  (good)
    state_ids=[] with a populated configuration -> LOADED
An emptied `state_ids` is exactly the "emptied ... silently lose" case, and
it is the field a tamperer would clear because it is the human-readable one.

This script pins which field WINS on restore, and whether the restored machine
behaves according to the surviving field.
"""
import copy, json, logging, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import (
    SnapshotCorruptError,
    SnapshotDriftError,
    SnapshotMidStepError,
    SnapshotVersionError,
)

TYPED = (
    SnapshotCorruptError,
    SnapshotDriftError,
    SnapshotVersionError,
    SnapshotMidStepError,
)

CFG = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {
            "initial": "c",
            "states": {"c": {"on": {"NEXT": "d"}}, "d": {}},
        },
    },
}


def fresh():
    return create_machine(copy.deepcopy(CFG), logic=MachineLogic())


def blob_at(*evs):
    it = SyncInterpreter(fresh())
    it.start()
    for e in evs:
        it.send(e)
    b = it.get_persisted_snapshot()
    it.stop()
    return b if isinstance(b, dict) else json.loads(b)


def restore(d):
    try:
        it = SyncInterpreter.from_snapshot(json.dumps(d), fresh())
    except TYPED as e:
        return ("refused", type(e).__name__, None)
    except Exception as e:
        return ("untyped", type(e).__name__, None)
    ids = sorted(it.current_state_ids)
    # Behaviour probe: does the restored machine ACT from the restored leaf?
    try:
        it.send("NEXT")
        after = sorted(it.current_state_ids)
    except Exception as e:
        after = f"send-raised:{type(e).__name__}"
    try:
        it.stop()
    except Exception:
        pass
    return ("loaded", ids, after)


at_c = blob_at("GO")  # leaf m.b.c
at_d = blob_at("GO", "NEXT")  # leaf m.b.d
print(f"clean@c  configuration={at_c['configuration']} state_ids={at_c['state_ids']}")
print(f"clean@d  configuration={at_d['configuration']} state_ids={at_d['state_ids']}")
print()

cases = {
    "baseline @c (untouched)": lambda: copy.deepcopy(at_c),
    "state_ids=[]  (config says m.b.c)": lambda: {
        **copy.deepcopy(at_c),
        "state_ids": [],
    },
    "state_ids missing (config says m.b.c)": lambda: {
        k: v for k, v in copy.deepcopy(at_c).items() if k != "state_ids"
    },
    "configuration=None (state_ids m.b.c)": lambda: {
        **copy.deepcopy(at_c),
        "configuration": None,
    },
    "configuration missing (state_ids m.b.c)": lambda: {
        k: v for k, v in copy.deepcopy(at_c).items() if k != "configuration"
    },
    "CROSS: config@d + state_ids@c": lambda: {
        **copy.deepcopy(at_c),
        "configuration": copy.deepcopy(at_d["configuration"]),
    },
    "CROSS: config@c + state_ids@d": lambda: {
        **copy.deepcopy(at_c),
        "state_ids": copy.deepcopy(at_d["state_ids"]),
    },
    "BOTH emptied": lambda: {
        **copy.deepcopy(at_c),
        "configuration": [],
        "state_ids": [],
    },
    "state_ids=[] AND configuration=None": lambda: {
        **copy.deepcopy(at_c),
        "configuration": None,
        "state_ids": [],
    },
}
bad = []
for name, f in cases.items():
    out = restore(f())
    note = ""
    if out[0] == "loaded" and "baseline" not in name:
        note = "  <== ACCEPTED"
        bad.append(name)
    if out[0] == "untyped":
        note = "  <== UNTYPED"
        bad.append(name)
    print(f"  {name:<40} -> {out[0]}:{out[1]} then NEXT->{out[2]}{note}")
print(f"\n  ACCEPTED-despite-disagreement / untyped: {len(bad)}")
for b in bad:
    print(f"     {b}")
