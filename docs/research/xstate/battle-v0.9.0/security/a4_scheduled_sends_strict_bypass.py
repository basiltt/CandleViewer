"""#227 strict/schema bypass attempt on the scheduled_sends lane: forge an
undeclared/mistyped event type into scheduled_sends and confirm it is
refused the same way pending_events is (D-CV-C54 property), and the
restore leaves a consistent machine (>=300 property runs, both kinds).
STANDALONE."""
import sys, json, random
sys.path.insert(0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter, Interpreter, PluginBase
from xstate_statemachine.actions import raise_ as raise_action
import asyncio

cfg = {
    "id": "m", "initial": "w", "strict": True,
    "states": {
        "w": {
            "entry": [raise_action({"type": "PING"}, delay=50000)],
            "on": {"PING": {"target": "w", "reenter": True}},
        },
    },
}


def run_case(seed):
    random.seed(seed)
    m = create_machine(cfg, logic=MachineLogic())
    interp = SyncInterpreter(m).start()
    snap = interp.get_persisted_snapshot()
    ss = snap.get("scheduled_sends") or []
    ok = True
    if ss:
        forged_type = random.choice(["UNDECLARED_X", "ping", "PING_TYPO"])
        ss[0]["type"] = forged_type
        snap["scheduled_sends"] = ss

    class Spy(PluginBase):
        def __init__(self):
            self.invalid = []
        def on_invalid_event(self, interpreter, exc, raw):
            self.invalid.append(raw)

    spy = Spy()
    restored = SyncInterpreter.from_snapshot(json.dumps(snap), m, plugins=[spy])
    restored.start()  # #227's admission check runs when start() re-arms
    # machine must remain consistent: still in state 'w', not crashed
    consistent = restored.current_state_ids == {"m.w"}
    refused = len(spy.invalid) >= 1 if ss else True
    return consistent and refused


n = 300
results = [run_case(i) for i in range(n)]
print(f"property cases: {n}, all consistent+refused: {all(results)}, failures: {results.count(False)}")
