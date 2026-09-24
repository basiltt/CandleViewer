"""N6 -- status of the prior D-fuzz defects that repros.py could no longer even
set up on 3ed3099, plus the surviving persistence gaps.

  * D-fuzz-2 / D-fuzz-10: root-targeting configs are now rejected at BUILD, so
    the old repro raised InvalidConfigError during setup ("harness error").
    We confirm the rejection is the fix, not a masking of the runtime path.
  * D-fuzz-7: from_snapshot loading garbage silently -- re-probed field by field.
  * D-fuzz-9: transient-settle trip leaving a non-tree configuration.
  * A14b: a non-JSON context value passes through get_persisted_snapshot().
"""
from __future__ import annotations
import copy, json, logging, warnings
warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (SyncInterpreter, Interpreter, MachineLogic,
                                 XStateMachineError, create_machine)
import xstate_statemachine as X

PING = {"id": "m", "initial": "a", "context": {"n": 0},
        "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"BACK": "a"}}}}


def L():
    return MachineLogic(services={"svc": lambda i, c, e: {"ok": 1}})


print("=== D-fuzz-2 / D-fuzz-10: root-targeting configs ===")
ROOTS = {
    "on -> #m": {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "#m"}}}},
    "always -> #m": {"id": "m", "initial": "a", "states": {"a": {"always": "#m"}}},
    "nested always -> #m": {"id": "m", "initial": "b",
                            "states": {"b": {"initial": "a",
                                             "states": {"a": {"always": "#m"}}}}},
}
for name, cfg in ROOTS.items():
    try:
        create_machine(copy.deepcopy(cfg), logic=L())
        print(f"  {name:24} -> BUILT (runtime path still reachable)")
    except XStateMachineError as e:
        print(f"  {name:24} -> rejected at build: {type(e).__name__}")
    except BaseException as e:
        print(f"  {name:24} -> UNTYPED {type(e).__name__}")
# strict_targets=False must not be an escape hatch back into the defect.
try:
    m = create_machine(copy.deepcopy(ROOTS["on -> #m"]), logic=L(),
                       strict_targets=False)
    it = SyncInterpreter(m)
    it.start()
    it.send("GO")
    print(f"  strict_targets=False     -> BUILT+SENT: states={sorted(it.current_state_ids)} "
          f"status={it.status} last_transition_ok={it.last_transition_ok}")
except XStateMachineError as e:
    print(f"  strict_targets=False     -> {type(e).__name__}")
except BaseException as e:
    print(f"  strict_targets=False     -> UNTYPED {type(e).__name__}: {e}")

print("\n=== D-fuzz-7: does from_snapshot still load garbage silently? ===")
it = SyncInterpreter(create_machine(copy.deepcopy(PING), logic=L()))
it.start()
clean = it.get_persisted_snapshot()
CASES = {
    "configuration=[]": ("configuration", []),
    "configuration=None": ("configuration", None),
    "configuration={}": ("configuration", {}),
    "state_ids=[]": ("state_ids", []),
    "status=5": ("status", 5),
    "status=None": ("status", None),
    "status=['running']": ("status", ["running"]),
    "status='banana'": ("status", "banana"),
    "context=42": ("context", 42),
    "context=None": ("context", None),
    "context='str'": ("context", "str"),
    "value=None": ("value", None),
    "actors={'a': None}": ("actors", {"a": None}),
    "actors=7": ("actors", 7),
    "history='junk'": ("history", "junk"),
    "history={'m': None}": ("history", {"m": None}),
    "deferred=[None]": ("deferred", [None]),
    "pending_events=[{}]": ("pending_events", [{}]),
    "output=<obj>": ("output", {"a": 1}),
}
silent, untyped, typed = [], [], []
for name, (k, v) in CASES.items():
    s = copy.deepcopy(clean)
    s[k] = v
    try:
        r = SyncInterpreter.from_snapshot(
            json.dumps(s), create_machine(copy.deepcopy(PING), logic=L()))
        ids = sorted(getattr(r, "current_state_ids", []) or [])
        print(f"  {name:24} -> LOADED  status={getattr(r,'status',None)!r} states={ids}")
        silent.append(name)
    except XStateMachineError as e:
        print(f"  {name:24} -> typed {type(e).__name__}")
        typed.append(name)
    except BaseException as e:
        print(f"  {name:24} -> UNTYPED {type(e).__name__}: {e}")
        untyped.append(name)
print(f"  summary: typed={len(typed)} silent={len(silent)} untyped={len(untyped)}")
print(f"  silent : {silent}")
print(f"  untyped: {untyped}")

print("\n=== D-fuzz-9: does a settle trip leave a non-tree configuration? ===")
# The 5e07ba8 shape: cross-region `always` into a sibling region's invoking
# state, with a tight maxIterations so the budget trips rather than hangs.
CROSS = {"id": "m", "type": "parallel", "maxIterations": 8,
         "states": {
             "A": {"initial": "a1",
                   "states": {"a1": {"invoke": {"id": "inv", "src": "svc",
                                                "onDone": "#m.A.a1"}}}},
             "B": {"initial": "b1",
                   "states": {"b1": {"always": "#m.A.a1"}}}}}
try:
    m = create_machine(copy.deepcopy(CROSS), logic=L())
    it2 = SyncInterpreter(m)
    import threading
    th = threading.Thread(target=it2.start, daemon=True)
    th.start()
    th.join(8)
    if th.is_alive():
        print("  start() STILL RUNNING after 8s (non-terminating)")
    else:
        ids = sorted(it2.current_state_ids)
        allids = {n.id for n in it2._active_state_nodes}
        orphans = [n.id for n in it2._active_state_nodes
                   if n.parent is not None and n.parent.id not in allids]
        print(f"  settled: states={ids} status={it2.status} "
              f"last_transition_ok={it2.last_transition_ok} "
              f"last_error={type(it2.last_error).__name__ if it2.last_error else None}")
        print(f"  orphans (active node with inactive parent): {orphans}")
except XStateMachineError as e:
    print(f"  rejected at build: {type(e).__name__}: {str(e)[:160]}")
except BaseException as e:
    print(f"  UNTYPED {type(e).__name__}: {e}")

print("\n=== A14b: non-JSON context value through get_persisted_snapshot() ===")
it3 = SyncInterpreter(create_machine(copy.deepcopy(PING), logic=L()))
it3.start()
it3.context["blob"] = object()
try:
    snap = it3.get_persisted_snapshot()
    print(f"  snapshot taken. context['blob'] = {snap['context']['blob']!r}")
    try:
        json.dumps(snap)
        print("  json.dumps(snapshot) -> OK")
    except BaseException as e:
        print(f"  json.dumps(snapshot) -> {type(e).__name__}: {e}")
        print("  => the caller's persist step, not the library, is where this fails")
except XStateMachineError as e:
    print(f"  typed {type(e).__name__}")
