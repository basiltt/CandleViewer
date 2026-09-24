"""NEW (f28719c): #198 - a version>=1 RUNNING snapshot must carry BOTH
configuration fields non-empty; a v0 payload keeps the state_ids-only
shape. Confirm the asymmetry fix (R8-08/#198) actually closed emptied-field
laundering on this commit.
STANDALONE: stdlib + xstate_statemachine only."""
import sys, json, warnings
warnings.simplefilter("ignore")
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.exceptions import XStateMachineError

CFG = {"id": "m", "initial": "a", "context": {},
       "states": {"a": {"on": {"GO": "b"}},
                   "b": {"initial": "c",
                         "states": {"c": {"on": {"GO2": "d"}}, "d": {}}}}}

def make():
    return create_machine(CFG, logic=MachineLogic())

m = make()
interp = SyncInterpreter(m).start()
interp.send("GO"); interp.send("GO2")
good = json.loads(interp.get_snapshot())
print("good shape keys:", sorted(good.keys()))

def try_restore(blob, label):
    try:
        m2 = make()
        i2 = SyncInterpreter.from_snapshot(json.dumps(blob), m2)
        print(f"{label}: ACCEPTED -> {i2.current_state_ids}")
        return True
    except XStateMachineError as e:
        print(f"{label}: REFUSED {type(e).__name__}")
        return False
    except Exception as e:
        print(f"{label}: UNCONTROLLED {type(e).__name__} {e}")
        return False

import copy
# a) state_ids emptied, configuration says m.b.d
b1 = copy.deepcopy(good); b1["state_ids"] = []
try_restore(b1, "state_ids=[] (config says leaf)")

# b) configuration removed entirely, state_ids intact
b2 = copy.deepcopy(good); b2.pop("configuration", None)
try_restore(b2, "configuration key removed")

# c) configuration emptied, state_ids intact
b3 = copy.deepcopy(good); b3["configuration"] = []
try_restore(b3, "configuration=[] (state_ids says leaf)")

# d) both present but disagree (cross)
b4 = copy.deepcopy(good); b4["configuration"] = ["m", "m.a"]
try_restore(b4, "configuration=@a while state_ids=@d (cross-contradiction)")
