import sys, json
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.exceptions import SnapshotCorruptError

cfg = {"id": "m", "initial": "a", "context": {"n": 0},
       "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"GO": "a"}}}}
m = create_machine(cfg, logic=MachineLogic())
interp = SyncInterpreter(m).start()
interp.send("GO")
good = json.loads(interp.get_snapshot())
print("GOOD KEYS:", list(good.keys()))

for k, v in [("taken_at", None), ("taken_at", "not-a-number"),
             ("machine_hash", None), ("chain_budget", "not-a-number")]:
    bad = dict(good)
    bad[k] = v
    s = json.dumps(bad, default=str)
    try:
        SyncInterpreter.from_snapshot(s, m)
        print(k, "->", v, ": accepted (no error)")
    except SnapshotCorruptError as e:
        print(k, "->", v, ": SnapshotCorruptError (OK)")
    except Exception as e:
        print(k, "->", v, f": UNCONTROLLED {type(e).__name__}: {e}")
