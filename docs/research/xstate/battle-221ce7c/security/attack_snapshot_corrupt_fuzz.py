"""New attack: fuzz get_persisted_snapshot()/from_snapshot() with mutated
payloads (reduced to 300 mutations for time budget) - every malformed
snapshot must raise SnapshotCorruptError (#110), never silently produce a
broken-but-"running" interpreter, and never raise anything else uncontrolled
(e.g. KeyError/TypeError escaping to the caller as a bare crash) that could
be mistaken for a data/security issue."""
import sys, json, random, copy
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.exceptions import SnapshotCorruptError

cfg = {"id": "m", "initial": "a", "context": {"n": 0},
       "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"GO": "a"}}}}
m = create_machine(cfg, logic=MachineLogic())
interp = SyncInterpreter(m).start()
interp.send("GO")
good = json.loads(interp.get_snapshot())

random.seed(42)
N = 300
uncontrolled = []
accepted_bad = []

def mutate(d):
    d = copy.deepcopy(d)
    choice = random.randint(0, 6)
    keys = list(d.keys()) if isinstance(d, dict) else []
    if choice == 0 and keys:
        del d[random.choice(keys)]
    elif choice == 1 and keys:
        d[random.choice(keys)] = None
    elif choice == 2:
        d["status"] = "not_a_real_status_" + str(random.random())
    elif choice == 3:
        d["state_ids"] = []
    elif choice == 4:
        d["context"] = "not-a-dict"
    elif choice == 5:
        d["__extra_junk__"] = {"a": [1, 2, {"b": object.__repr__(object())}]}
    elif choice == 6 and keys:
        k = random.choice(keys)
        if isinstance(d.get(k), (int, float)):
            d[k] = "not-a-number"
    return d

for i in range(N):
    bad = mutate(good)
    s = json.dumps(bad, default=str)
    try:
        SyncInterpreter.from_snapshot(s, m)
        accepted_bad.append((i, s[:200]))
    except SnapshotCorruptError:
        pass
    except Exception as e:
        uncontrolled.append((i, type(e).__name__, str(e)[:150]))

print(f"mutations={N} accepted_bad={len(accepted_bad)} uncontrolled_exceptions={len(uncontrolled)}")
for i, name, msg in uncontrolled[:15]:
    print(" UNCONTROLLED:", i, name, msg)
for i, s in accepted_bad[:5]:
    print(" ACCEPTED_BAD:", i, s)
