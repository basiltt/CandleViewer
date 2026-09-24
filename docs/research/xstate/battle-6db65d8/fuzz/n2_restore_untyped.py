"""D5-fuzz-2 repro: from_snapshot() still raises untyped AttributeError/TypeError
for junk in `_actor_snapshots`/`history`/`deferred`/`state_ids`-adjacent fields."""
import copy, json, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import (create_machine, SyncInterpreter, MachineLogic,
                                 XStateMachineError)

CFG = {"id":"m","initial":"a","states":{"a":{"on":{"GO":"b"}},"b":{}}}
LOGIC = MachineLogic()
m = create_machine(copy.deepcopy(CFG), logic=LOGIC)
it = SyncInterpreter(m); it.start()
snap = it.get_persisted_snapshot()
if isinstance(snap, str): snap = json.loads(snap)
print("clean snapshot keys:", sorted(snap))

MUTATIONS = {
  "history=str":            lambda s: s.__setitem__("history", "junk"),
  "history={'m':None}":     lambda s: s.__setitem__("history", {"m": None}),
  "actors={'a':None}":      lambda s: s.__setitem__("actors", {"a": None}),
  "actors=7":               lambda s: s.__setitem__("actors", 7),
  "deferred=[None]":        lambda s: s.__setitem__("deferred", [None]),
  "state_ids=None":         lambda s: s.__setitem__("state_ids", None),
  "configuration=None":     lambda s: s.__setitem__("configuration", None),
}
fails = 0
for name, mut in MUTATIONS.items():
    s = copy.deepcopy(snap)
    try: mut(s)
    except Exception as e: print(f"  {name:24} skip ({e})"); continue
    try:
        _r = SyncInterpreter.from_snapshot(json.dumps(s), m)
        print(f"  {name:24} -> LOADED SILENTLY  (config={sorted(getattr(_r,'current_state_ids',[]) or [])}, status={getattr(_r,'status',None)})")
        fails += 1
    except XStateMachineError as e:
        print(f"  {name:24} -> typed {type(e).__name__}")
    except BaseException as e:
        print(f"  {name:24} -> UNTYPED {type(e).__name__}: {e}")
        fails += 1
print("non-contractual outcomes:", fails, "/", len(MUTATIONS))
