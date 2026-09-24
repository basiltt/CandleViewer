# -*- coding: utf-8 -*-
"""Q2 -- read-side validation gaps R6-07 / R6-16 re-attacked on 221ce7c.

R6-07: `machine_hash: None` disables drift verification even under
       `verify_machine_hash=True` (persistence.py:277).
R6-16: `configuration` is never cross-validated against `state_ids`.

Both were filed against `cec108b` and are NOT listed in the round-6 fix set
(#166-#175); this script re-establishes their status on 221ce7c.
"""
from __future__ import annotations

import json

from xstate_statemachine import SyncInterpreter, create_machine
from xstate_statemachine.exceptions import XStateMachineError

A = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"GO": "b"}}, "b": {}},
}
# structurally DIFFERENT machine, same id -> hash must differ
B = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"GO": "c"}}, "c": {"on": {"X": "a"}}},
}


def snap():
    i = SyncInterpreter(create_machine(json.loads(json.dumps(A))))
    i.start()
    b = i.get_persisted_snapshot()
    i.stop()
    return b


def attempt(label, blob, cfg, **kw):
    try:
        r = SyncInterpreter.from_snapshot(
            json.dumps(blob), create_machine(json.loads(json.dumps(cfg))), **kw
        )
        print(
            f"  {label:46s} ACCEPTED  states="
            f"{sorted(n.id for n in r._active_state_nodes)}"
        )
        return True
    except XStateMachineError as e:
        print(f"  {label:46s} {type(e).__name__}")
        return False


fails = []

print("=== R6-07: machine_hash dropped, restored into a DIFFERENT machine")
base = snap()
print(f"  (snapshot machine_hash = {base.get('machine_hash')!r})")
honest = dict(base)
ok_honest = attempt("honest hash vs machine B", honest, B)
if ok_honest:
    fails.append("R6-07 control: wrong-hash restore was accepted")

dropped = dict(base)
dropped["machine_hash"] = None
if attempt("machine_hash=None vs machine B", dropped, B):
    fails.append("R6-07: machine_hash=None disables drift check")

removed = dict(base)
removed.pop("machine_hash", None)
if attempt("machine_hash key REMOVED vs machine B", removed, B):
    fails.append("R6-07b: missing machine_hash key disables drift check")

print()
print("=== R6-16: `configuration` contradicts `state_ids`")
c1 = dict(base)
c1["configuration"] = []
if attempt("configuration=[] (state_ids intact)", c1, A):
    fails.append("R6-16: empty configuration not cross-checked")

c2 = dict(base)
c2["configuration"] = ["m", "m.b"]  # contradicts state_ids ['m','m.a']
if attempt("configuration=['m','m.b'] vs state_ids a", c2, A):
    fails.append("R6-16b: contradictory configuration not cross-checked")

print()
print(f"  state_ids in snapshot     = {base.get('state_ids')}")
print(f"  configuration in snapshot = {base.get('configuration')}")
print()
for f in fails:
    print("  STILL-PRESENT:", f)
print("VERDICT:", "PASS" if not fails else f"FAIL ({len(fails)})")
