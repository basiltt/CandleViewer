"""D5-semantics-3 repro: a snapshot whose `configuration` list is TRUNCATED
(the leaf removed, ancestors kept) passes check_shape and restores to an
EMPTY configuration reporting status='running' -- the exact #102 failure mode,
reached through a corrupt blob instead of a mid-step snapshot.

Every other poisoning of that slot is caught (None -> SnapshotCorruptError,
"" / "xxx" -> StateNotFoundError). Only DELETION slips through, because
check_shape validates element TYPES but never that the configuration contains
at least one leaf of the machine.

The restored machine accepts events forever, changes nothing, reports no
error and reports `running`. For an OMS that is a silently dead order actor.
"""
import json, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

CFG = {"id": "oms", "initial": "new", "context": {"qty": 0},
       "states": {"new": {"on": {"FILL": "filled"}},
                  "filled": {"on": {"FILL": "new"}}}}
mk = lambda: create_machine(CFG, logic=MachineLogic())

s = SyncInterpreter(mk()).start(); s.send("FILL")
base = s.get_persisted_snapshot(); s.stop()
print(f"healthy snapshot: configuration={base['configuration']} state_ids={base['state_ids']}")

for label, mutate in [
    ("leaf -> None", lambda b: b["configuration"].__setitem__(1, None)),
    ("leaf -> ''",   lambda b: b["configuration"].__setitem__(1, "")),
    ("leaf -> 'xxx'", lambda b: b["configuration"].__setitem__(1, "xxx")),
    ("leaf DELETED", lambda b: b["configuration"].__delitem__(1)),
]:
    b = json.loads(json.dumps(base))
    mutate(b)
    try:
        r = SyncInterpreter.from_snapshot(json.dumps(b), mk()); r.start()
        print(f"  {label:15} -> ACCEPTED ids={sorted(r.current_state_ids)} status={r.status!r}")
        for n in range(3):
            rec = r.send("FILL")
        print(f"  {'':15}    after 3x FILL: ids={sorted(r.current_state_ids)} "
              f"ctx={r.context} last_transition_ok={r.last_transition_ok} "
              f"last_error={r.last_error} status={r.status!r}")
        print(f"  {'':15}    >>> INERT but reports running -- #102's failure mode via a corrupt blob")
        r.stop()
    except Exception as e:
        print(f"  {label:15} -> {type(e).__name__}: {str(e)[:80]}")
