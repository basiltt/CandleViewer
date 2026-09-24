"""N7 -- when from_snapshot accepts a blob whose configuration/state_ids were
tampered to empty, WHICH state does the restored machine land in?"""
import copy, json, logging, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import SyncInterpreter, MachineLogic, create_machine, XStateMachineError

PING = {"id":"m","initial":"a","context":{"n":0},
        "states":{"a":{"on":{"GO":"b"}},"b":{"on":{"BACK":"a"}}}}
L = lambda: MachineLogic()

it = SyncInterpreter(create_machine(copy.deepcopy(PING), logic=L())); it.start()
it.send("GO")
print("live machine is in:", sorted(it.current_state_ids))
clean = it.get_persisted_snapshot()
print("clean snapshot: configuration=%r state_ids=%r value=%r" %
      (clean.get("configuration"), clean.get("state_ids"), clean.get("value")))

for name, muts in {
    "configuration=[]": {"configuration": []},
    "configuration=None": {"configuration": None},
    "state_ids=[]": {"state_ids": []},
    "configuration=[] AND state_ids=[]": {"configuration": [], "state_ids": []},
    "value=None": {"value": None},
}.items():
    s = copy.deepcopy(clean); s.update(muts)
    try:
        r = SyncInterpreter.from_snapshot(json.dumps(s), create_machine(copy.deepcopy(PING), logic=L()))
        got = sorted(r.current_state_ids)
        verdict = "CORRECT" if got == ["m.b"] else "WRONG STATE (silently)"
        print(f"  {name:36} -> LOADED states={got} status={r.status}  [{verdict}]")
    except XStateMachineError as e:
        print(f"  {name:36} -> typed {type(e).__name__}")
    except BaseException as e:
        print(f"  {name:36} -> UNTYPED {type(e).__name__}: {e}")
