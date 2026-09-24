"""T-3 probe: check_shape on chain_trips edge values."""
import os
from xstate_statemachine import create_machine, SyncInterpreter, SnapshotCorruptError
os.chdir("C:/Users/basil")
m = create_machine({"id": "m", "initial": "a", "states": {"a": {}}})
it = SyncInterpreter(m).start(); base = it.get_snapshot(); it.stop()
import json
for v in ["1e3", "-0", " 7 ", "+3", "٣", "1_000", 3.0, 2.5, -1, "-1", 10**30]:
    s = json.loads(base) if isinstance(base, str) else dict(base)
    s["chain_trips"] = v
    try:
        r = SyncInterpreter.from_snapshot(json.dumps(s) if isinstance(base, str) else s, m)
        print(repr(v), "-> accepted chain_trips =", r.chain_trips)
    except SnapshotCorruptError as e: print(repr(v), "-> SnapshotCorruptError")
    except Exception as e: print(repr(v), "-> RAW", type(e).__name__, e)
