"""Re-verify R9-01 (engine-completion provenance forgeable) and R9-02
(after.* matched on public class) against 19cb1f1 (round-9 fix set
#203-#210). Neither issue number appears in the round-9 CHANGELOG entry,
so this checks whether they still hold unchanged, or were incidentally
closed. STANDALONE: stdlib + xstate_statemachine only."""
import sys, copy, pickle
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.events import AfterEvent, DoneEvent

# --- R9-02: hand-built public AfterEvent fires an after-transition instantly ---
cfg_after = {
    "id": "m", "initial": "waiting",
    "states": {
        "waiting": {"after": {60000: "expired"}, "on": {"PING": "waiting"}},
        "expired": {"type": "final"},
    },
}
m1 = create_machine(cfg_after, logic=MachineLogic())
interp1 = SyncInterpreter(m1).start()
forged_after = AfterEvent("after.60000.m.waiting", None, None)
interp1.send(forged_after)
r902_bypassed = interp1.current_state_ids == {"m.expired"}
print("R9-02 forged public AfterEvent fires after-transition:", r902_bypassed,
      "state=", interp1.current_state_ids)

# --- R9-01 vector 1: NamedTuple._replace re-types a harmless completion ---
cfg_done = {
    "id": "m", "initial": "idle",
    "invoke": {"id": "svc", "src": "ping", "onDone": "done_state"},
    "states": {"idle": {}, "done_state": {"type": "final"}},
}
captured = {}
def ping(i, c, e, a):
    def _run():
        return {"real": True}
    return _run

logic = MachineLogic(services={"ping": ping})
m2 = create_machine(cfg_done, logic=logic)
interp2 = SyncInterpreter(m2).start()

# capture a genuine DoneEvent instance by monkeypatching send to snoop, then
# attempt _replace forgery on a hand-copied public DoneEvent (not engine-minted)
genuine_shape = DoneEvent("done.invoke.svc", {"real": True}, "svc")
try:
    forged = genuine_shape._replace(data={"forged": True})
    from xstate_statemachine.events import is_system_event
    r901_v1 = is_system_event(forged)
except Exception as e:
    r901_v1 = f"ERROR:{e}"
print("R9-01 vector1 (_replace on PUBLIC DoneEvent) is_system_event:", r901_v1,
      "(expect False if #195 boundary intact: public class never trusted)")

# --- R9-01 vector: pickle round-trip of a PUBLIC DoneEvent (not engine-minted) ---
pk = pickle.loads(pickle.dumps(genuine_shape))
from xstate_statemachine.events import is_system_event
print("R9-01 vector-pickle (public DoneEvent pickled) is_system_event:",
      is_system_event(pk))

# --- can user code reach the private _EngineDone class at all? ---
try:
    import xstate_statemachine.events as ev_mod
    priv = ev_mod._EngineDone
    forged2 = priv("done.invoke.svc", {"forged": True}, "svc")
    print("R9-01 vector-import (_EngineDone importable, constructible):", True,
          "is_system_event=", is_system_event(forged2))
except Exception as e:
    print("R9-01 vector-import:", f"ERROR:{e}")

print("interp2 final state (genuine service, no forgery injected into it):",
      interp2.current_state_ids)

# --- R9-01 decisive test on async engine: import-path _EngineDone forgery
# while a genuine service is STILL RUNNING (the exact OMS-relevant shape) ---
import asyncio
from xstate_statemachine import Interpreter

cfg3 = {
    "id": "m", "initial": "idle",
    "invoke": {"id": "svc", "src": "slow", "onDone": "done_state"},
    "states": {"idle": {}, "done_state": {"type": "final"}},
}
async def slow(i, c, e):
    await asyncio.sleep(3)
    return {"real": True}

logic3 = MachineLogic(services={"slow": slow})
m3 = create_machine(cfg3, logic=logic3)

async def main():
    interp3 = Interpreter(m3)
    await interp3.start()
    await asyncio.sleep(0.2)  # genuine service in flight, not yet resolved
    forged3 = ev_mod._EngineDone("done.invoke.svc", {"forged": True}, "svc")
    interp3.send(forged3)
    await asyncio.sleep(0.2)
    forged_landed = interp3.current_state_ids == {"m.done_state"}
    print("R9-01 DECISIVE (import-path _EngineDone forgery while genuine "
          "service still running, async engine): forged onDone fired =",
          forged_landed, "state=", interp3.current_state_ids)
    await asyncio.sleep(3.2)  # let genuine completion window pass
    print("  after genuine-completion window (no crash expected, already final):",
          interp3.current_state_ids)
    await interp3.stop()

import xstate_statemachine.events as ev_mod
asyncio.run(main())

