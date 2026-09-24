"""Re-verify R9-07 (rollback+onDone storm silently wedges below default
maxIterations, no RunawayChainError observable) against 19cb1f1's claimed
fix (#207: RunawayChainError.stranded + on_invocation_stranded hook + ERROR
log). Runs both service kinds (def/async def), both engines.
STANDALONE: stdlib + xstate_statemachine only."""
import asyncio, json, sys
sys.path.insert(0, "src")
from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine, PluginBase
from xstate_statemachine.exceptions import RunawayChainError

BASE = {
    "id": "r6", "actionErrorPolicy": "rollback", "onUnhandled": "defer",
    "guardErrorPolicy": "raise", "strictTargets": True, "strict": True,
    "initial": "idle", "context": {},
    "states": {
        "idle": {"on": {"GO": {"target": "#r6.starting"}}},
        "starting": {"invoke": {"id": "sub", "src": "svc",
                                "onDone": {"target": "#r6.recording"},
                                "onError": {"target": "#r6.err"}}},
        "recording": {"entry": ["boom"]},
        "err": {},
    },
}

class StrandHook(PluginBase):
    def __init__(self):
        self.calls = []
    def on_invocation_stranded(self, interpreter, state_id, invoke_id, error):
        self.calls.append((state_id, invoke_id, type(error).__name__))

def make(counter, style, max_iter=None):
    def boom(i, c, e, a):
        counter["boom"] += 1
        raise RuntimeError("entry failed")
    if style == "def":
        def svc(i, c, e):
            counter["svc"] += 1
            return {"ok": True}
    else:
        async def svc(i, c, e):
            counter["svc"] += 1
            return {"ok": True}
    cfg = json.loads(json.dumps(BASE))
    if max_iter is not None:
        cfg["maxIterations"] = max_iter
    logic = MachineLogic(actions={"boom": boom}, services={"svc": svc})
    return create_machine(cfg, logic=logic), logic

async def run_async(style):
    counter = {"boom": 0, "svc": 0}
    machine, logic = make(counter, style)
    hook = StrandHook()
    interp = Interpreter(machine)
    interp.use(hook)
    await interp.start()
    interp.send("GO")
    await asyncio.sleep(1.0)
    result = {
        "style": style, "engine": "async",
        "state": sorted(interp.current_state_ids),
        "last_error_type": type(interp.last_error).__name__ if interp.last_error else None,
        "stranded_attr": getattr(interp.last_error, "stranded", "N/A") if interp.last_error else None,
        "hook_calls": hook.calls,
        "has_dormant": interp.has_dormant_invocations if hasattr(interp, "has_dormant_invocations") else "N/A",
        "pending_invocations": list(interp.pending_invocations()) if hasattr(interp, "pending_invocations") else "N/A",
    }
    await interp.stop()
    return result

def run_sync(style):
    counter = {"boom": 0, "svc": 0}
    machine, logic = make(counter, style)
    hook = StrandHook()
    interp = SyncInterpreter(machine)
    interp.use(hook)
    interp.start()
    interp.send("GO")
    result = {
        "style": style, "engine": "sync",
        "state": sorted(interp.current_state_ids),
        "last_error_type": type(interp.last_error).__name__ if interp.last_error else None,
        "stranded_attr": getattr(interp.last_error, "stranded", "N/A") if interp.last_error else None,
        "hook_calls": hook.calls,
        "has_dormant": interp.has_dormant_invocations if hasattr(interp, "has_dormant_invocations") else "N/A",
        "pending_invocations": list(interp.pending_invocations()) if hasattr(interp, "pending_invocations") else "N/A",
    }
    interp.stop()
    return result

for style in ("def", "async"):
    r = asyncio.run(run_async(style))
    print(r)
r = run_sync("def")
print(r)
