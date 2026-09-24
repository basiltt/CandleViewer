"""R4-30: a deferred event's replay folds into the triggering event's own
Receipt. The replay loop (interpreter.py `_process_event_and_transient_
transitions`, "3. Replay deferred events...") runs inside the same run-loop
iteration as the triggering event, before that event's own receipt is
resolved (`_resolve_receipt` runs after `_process_event_and_transient_
transitions` returns, interpreter.py ~1271-1280).

EXPECTED: send("ARM", wait=True) should return a Receipt describing ARM's
OWN transition (a -> b), not the state reached after a deferred event
replayed on top of it.
OBSERVED: the Receipt for "ARM" reports the post-replay state (b -> c, from
replaying the earlier-deferred "LATE"), not ARM's own transition (a -> b).

Exits 1 while the defect is present, 0 once fixed.
"""
from __future__ import annotations

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

CFG = {
    "id": "m_defer_replay",
    "initial": "a",
    "onUnhandled": "defer",
    "states": {
        "a": {"on": {"ARM": "b"}},
        "b": {"on": {"LATE": "c"}},
        "c": {},
    },
}

machine = create_machine(CFG, logic=MachineLogic())
interp = SyncInterpreter(machine).start()

r_late_initial = interp.send("LATE", wait=True)  # deferred while in "a"
r_arm = interp.send("ARM", wait=True)  # a->b, triggers replay of LATE: b->c

print(f"receipt for deferred LATE (queued): {r_late_initial}")
print(f"receipt for ARM                   : {r_arm}")
print(f"final state                       : {sorted(interp.current_state_ids)}")

arm_state_ids = set(r_arm.state_ids)
final_state_ids = set(interp.current_state_ids)
# ARM's own transition takes the machine to "b"; if the LATE replay folded
# into ARM's receipt, r_arm.state_ids will already report "c".
c_in_arm_receipt = any(sid.endswith(".c") or sid == "c" for sid in arm_state_ids)

print(f"\nARM receipt reports final state 'c' (post-replay): {c_in_arm_receipt}")

defect_present = c_in_arm_receipt
print(
    "OBSERVED:",
    "ARM's Receipt reflects the post-replay state, folding LATE's effect "
    "into ARM's own receipt"
    if defect_present
    else "ARM's Receipt reflects only its own transition",
)
print(
    "EXPECTED: ARM's Receipt reports only ARM's own transition (state 'b'); "
    "the replayed LATE event's effect should be separately attributable"
)
print("RESULT:", "FAIL - defect present" if defect_present else "PASS")

raise SystemExit(1 if defect_present else 0)
