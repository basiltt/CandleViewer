# -*- coding: utf-8 -*-
"""R7-09 -- a contradictory `configuration` key outranks `state_ids` on
restore. `base_interpreter.py:1689`:

    restore_ids = snapshot.get("configuration") or snapshot["state_ids"]

`configuration` is *preferred*, never cross-validated against `state_ids`.
The two fields are redundant by construction (`configuration` is the
ancestor closure of `state_ids`), so any disagreement between them is
evidence of corruption or a lossy transport -- but the restore path silently
resolves it in favour of `configuration`, discarding the honest field.

Library only, no project machinery. main @ 221ce7c (unreleased 0.8.1;
`__version__` still reports 0.8.0 -- key on the commit). Python 3.13.

Exit code 1 == a blob whose `configuration` contradicts its `state_ids` was
ACCEPTED and silently relocated the machine. Exit code 0 == refused.
"""
import json

from xstate_statemachine import SyncInterpreter, create_machine
from xstate_statemachine.exceptions import XStateMachineError

A = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"GO": "b"}}, "b": {}},
}


def snap():
    i = SyncInterpreter(create_machine(json.loads(json.dumps(A))))
    i.start()
    b = i.get_persisted_snapshot()
    i.stop()
    return b


def attempt(label, blob):
    try:
        r = SyncInterpreter.from_snapshot(
            json.dumps(blob), create_machine(json.loads(json.dumps(A)))
        )
        states = sorted(n.id for n in r._active_state_nodes)
        print("  %-46s ACCEPTED  states=%r" % (label, states))
        return True, states
    except XStateMachineError as exc:
        print("  %-46s %s" % (label, type(exc).__name__))
        return False, None


def main() -> int:
    base = snap()
    print("state_ids in snapshot     = %r" % (base.get("state_ids"),))
    print("configuration in snapshot = %r" % (base.get("configuration"),))
    print()

    fails = []

    c1 = dict(base)
    c1["configuration"] = []
    ok, states = attempt("configuration=[] (state_ids intact)", c1)
    if ok:
        fails.append(
            "configuration=[] fell back silently instead of being refused "
            "as a contradiction (states=%r)" % (states,)
        )

    c2 = dict(base)
    c2["configuration"] = ["m", "m.b"]  # contradicts state_ids ['m', 'm.a']
    ok, states = attempt("configuration=['m','m.b'] vs state_ids=['m','m.a']", c2)
    if ok:
        fails.append(
            "contradictory configuration relocated the machine to %r while "
            "state_ids explicitly said ['m', 'm.a']" % (states,)
        )

    print()
    if fails:
        for f in fails:
            print("REPRODUCED:", f)
        print("EXPECTED  : `from_snapshot` should refuse (SnapshotCorruptError) "
              "when `configuration` is not the ancestor closure of `state_ids`, "
              "rather than silently preferring `configuration`.")
        return 1
    print("NOT reproduced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
