# -*- coding: utf-8 -*-
"""R4-02: `from_snapshot()` performs no configuration-legality, status, or
context validation, and leaks raw builtin exceptions (KeyError/TypeError/
AttributeError) for malformed persisted-snapshot shapes instead of the
library's documented `XStateMachineError` catch-all.

Standalone, derived from battle-5e07ba8/fuzz/repros.py::d7 and
battle-5e07ba8/persistence/t3_probes.py::probe_corrupt (P7).

Exits 1 (defect present) if either:
  (a) a snapshot with an EMPTY configuration is accepted and produces a
      "running", healthy-looking interpreter with no active states, or
  (b) any of a set of malformed snapshot fields (status, context type,
      pending_events shape) escapes as a bare builtin exception instead of
      XStateMachineError.
Exits 0 once both are fixed.
"""
from __future__ import annotations

import copy
import json

from xstate_statemachine import SyncInterpreter, XStateMachineError, create_machine

CFG = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"GO": "#m.b"}}, "b": {}},
}


def main() -> int:
    machine = create_machine(CFG)
    i = SyncInterpreter(machine)
    i.start()
    snap = i.get_persisted_snapshot()

    findings = []

    # --- (a) empty configuration is silently accepted -----------------
    s_empty = copy.deepcopy(snap)
    s_empty.update({"configuration": [], "state_ids": []})
    r = SyncInterpreter.from_snapshot(
        json.dumps(s_empty, default=str), machine, verify_machine_hash=False
    )
    empty_accepted = r.status == "running" and sorted(r.current_state_ids) == []
    print(
        f"OBSERVED (a): empty configuration -> status={r.status!r} "
        f"states={sorted(r.current_state_ids)}"
    )
    print("EXPECTED (a): a typed XStateMachineError (e.g. InvalidConfigError)")
    findings.append(empty_accepted)

    # --- (b) malformed fields leak bare builtin exceptions --------------
    mutations = {
        "status='zzz'": {"status": "zzz"},
        "status=5": {"status": 5},
        "context=42": {"context": 42},
        "pending_events=[{}]": {"pending_events": [{}]},
        "pending_events=[null]": {"pending_events": [None]},
        'state_ids=[["m.a"]]': {"configuration": None, "state_ids": [["m.a"]]},
    }
    untyped = []
    for name, mut in mutations.items():
        s = copy.deepcopy(snap)
        s.update(mut)
        try:
            SyncInterpreter.from_snapshot(
                json.dumps(s, default=str), machine, verify_machine_hash=False
            )
            outcome = "ACCEPTED (no validation)"
        except XStateMachineError as exc:
            outcome = f"typed {type(exc).__name__}"
        except Exception as exc:  # noqa: BLE001
            outcome = f"UNTYPED {type(exc).__name__}: {exc}"
            untyped.append(name)
        print(f"OBSERVED (b) {name}: {outcome}")
    print("EXPECTED (b): every malformed field raises an XStateMachineError subclass")

    defect_present = empty_accepted or len(untyped) > 0
    print(
        f"\nVERDICT: empty_config_accepted={empty_accepted} "
        f"untyped_escapes={untyped}"
    )
    return 1 if defect_present else 0


if __name__ == "__main__":
    raise SystemExit(main())
