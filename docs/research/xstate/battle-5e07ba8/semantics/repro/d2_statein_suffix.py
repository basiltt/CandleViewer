"""D-semantics repro: `stateIn` matches by ID SUFFIX, not identity.

`_is_state_in` (base_interpreter.py:4220) accepts a node when
`node.id.endswith("." + target)`. A guard naming one branch is therefore
satisfied by an unrelated branch that happens to share trailing segments.
"""
import logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

CFG = {
  "id": "m", "initial": "p",
  "states": {"p": {"type": "parallel", "states": {
    "A": {"initial": "right", "states": {
        "left":  {"initial": "work", "states": {"work": {}}},
        "right": {"initial": "work", "states": {"work": {}}}}},
    "B": {"initial": "b1", "states": {
        "b1": {"on": {"E": {"target": "b2", "guard": {
                 "type": "stateIn",
                 # Names LEFT.work. Only RIGHT.work is active.
                 "params": {"state": "left.work"}}}}},
        "b2": {}}}}}}}

s = SyncInterpreter(create_machine(CFG, logic=MachineLogic())).start()
print("active   :", sorted(s.current_state_ids))
print("guard names 'left.work'; 'm.p.A.left.work' is NOT active")
s.send("E")
ids = sorted(s.current_state_ids)
print("after E  :", ids)
print("VERDICT  :", "DEFECT - guard fired on the wrong branch"
      if "m.p.B.b2" in ids else "ok")
s.stop()
