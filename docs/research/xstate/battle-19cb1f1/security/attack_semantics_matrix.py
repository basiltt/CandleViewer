"""New attacks on round-5 semantics fixes relevant to security/trust
boundary: RootTargetError non-downgradable under strict_targets=False,
'fail' actionErrorPolicy stops the machine (config cleared, snapshot
refused), guardErrorPolicy='raise' falls back to next candidate,
Receipt.denied distinguishes guard-refusal from undeclared-event."""
import sys, json
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.exceptions import (
    RootTargetError, SnapshotCorruptError, TransitionFailedError,
)

results = []

# 1. RootTargetError non-downgradable even with strict_targets=False
try:
    cfg = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "#m"}}}}
    m = create_machine(cfg, logic=MachineLogic(), strict_targets=False)
    results.append(("RootTargetError-nondowngrade", "FAIL-no-error-raised"))
except RootTargetError:
    results.append(("RootTargetError-nondowngrade", "OK-raised-even-with-strict_targets=False"))
except Exception as e:
    results.append(("RootTargetError-nondowngrade", f"UNEXPECTED {type(e).__name__}: {e}"))

# 2. actionErrorPolicy="fail" stops the machine; snapshot then refused/handled
def boom(interp, context, event, action_def):
    raise RuntimeError("boom")

cfg2 = {
    "id": "m2", "initial": "a", "context": {}, "actionErrorPolicy": "fail",
    "states": {"a": {"on": {"GO": {"target": "b", "actions": ["boom"]}}}, "b": {}},
}
m2 = create_machine(cfg2, logic=MachineLogic(actions={"boom": boom}))
interp2 = SyncInterpreter(m2).start()
interp2.send("GO")
status = interp2.status
try:
    snap = interp2.get_snapshot()
    snap_ok = True
    snap_json = json.loads(snap)
except Exception as e:
    snap_ok = False
    snap_json = {"error_class": type(e).__name__}
results.append(("fail-policy-status", status))
results.append(("fail-policy-snapshot-taken", snap_ok, snap_json.get("status") if snap_ok else snap_json))

# restore a "stopped"-with-error snapshot -- must not silently resume as running
if snap_ok:
    try:
        restored = SyncInterpreter.from_snapshot(snap, m2)
        results.append(("fail-snapshot-restore", f"restored status={restored.status}"))
    except Exception as e:
        results.append(("fail-snapshot-restore", f"{type(e).__name__}: {e}"))

# 3. guardErrorPolicy="raise": one candidate's guard raises, fallback taken
def raising_guard(context, event):
    raise ValueError("guard blew up")

cfg3 = {
    "id": "m3", "initial": "a", "context": {}, "guardErrorPolicy": "raise",
    "states": {
        "a": {
            "on": {
                "GO": [
                    {"target": "b", "guard": "boomGuard"},
                    {"target": "c"},
                ]
            }
        },
        "b": {}, "c": {},
    },
}
m3 = create_machine(cfg3, logic=MachineLogic(guards={"boomGuard": raising_guard}))
interp3 = SyncInterpreter(m3).start()
try:
    interp3.send("GO")
    results.append(("guardErrorPolicy-raise-fallback", f"landed={sorted(s.id for s in interp3._active_state_nodes if not s.states)} (no exception propagated)"))
except Exception as e:
    landed = sorted(s.id for s in interp3._active_state_nodes if not s.states)
    results.append(("guardErrorPolicy-raise-fallback", f"fallback_taken={landed} exception_propagated_to_caller={type(e).__name__}: {e} (matches #152 documented contract: fallback taken AND exception surfaced to sync send() caller)"))

# 4. Receipt.denied vs undeclared
cfg4 = {
    "id": "m4", "initial": "a", "context": {},
    "states": {"a": {"on": {"GO": {"target": "b", "guard": "alwaysFalse"}}}, "b": {}},
}
def always_false(context, event):
    return False
m4 = create_machine(cfg4, logic=MachineLogic(guards={"alwaysFalse": always_false}))
import asyncio
from xstate_statemachine import Interpreter

cfg4 = {
    "id": "m4", "initial": "a", "context": {},
    "states": {"a": {"on": {"GO": {"target": "b", "guard": "alwaysFalse"}}}, "b": {}},
}
m4 = create_machine(cfg4, logic=MachineLogic(guards={"alwaysFalse": always_false}))

async def receipt_matrix():
    interp4 = Interpreter(m4)
    await interp4.start()
    r_denied = await interp4.send("GO", wait=True)  # declared, guard refuses
    r_undeclared = await interp4.send("NOPE_UNDECLARED", wait=True)  # not declared
    await interp4.stop()
    return r_denied, r_undeclared

r_denied, r_undeclared = asyncio.run(receipt_matrix())
results.append(("Receipt.denied (guard refused)", r_denied.denied, r_denied.changed))
results.append(("Receipt.denied (undeclared event)", r_undeclared.denied, r_undeclared.changed))

for r in results:
    print(r)
