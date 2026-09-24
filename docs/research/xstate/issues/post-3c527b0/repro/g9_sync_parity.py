"""G-9: sync-engine parity for ErrorEvent + provenance."""
from xstate_statemachine import Event, MachineLogic, create_machine
from xstate_statemachine.sync_interpreter import SyncInterpreter
from xstate_statemachine.events import ErrorEvent

seen = []
def record(i, c, e, a=None):
    seen.append((type(e).__name__, e.type, getattr(e, "error", None)))

def blow(i, c, e): raise ValueError("sync boom")

CFG = {"id": "m", "initial": "w", "states": {
    "w": {"invoke": {"src": "svc", "id": "svc",
                     "onError": {"target": "bad", "actions": ["record"]}}},
    "bad": {}}}

it = SyncInterpreter(create_machine(CFG, logic=MachineLogic(
    services={"svc": blow}, actions={"record": record})))
it.start()
print("A sync service failure -> state", set(it.current_state_ids), "event seen:", seen)
print("  is ErrorEvent:", seen and seen[0][0] == "ErrorEvent")
it.stop()

# provenance in sync: forged system event vs strict
STRICT = {"id": "t", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
it2 = SyncInterpreter(create_machine(STRICT, logic=MachineLogic()), strict=True)
it2.start()
for lbl, e in (("plain ", Event("NOPE")), ("forged", Event("NOPE", system=True))):
    try:
        it2.send(e); print(f"B sync strict {lbl}: ACCEPTED")
    except Exception as exc: print(f"B sync strict {lbl}: {type(exc).__name__}")
it2.stop()

# sync "*" matcher
STAR = {"id": "s", "initial": "a", "states": {"a": {"on": {"*": "b"}}, "b": {}}}
for lbl, e in (("plain ", Event("X")), ("forged", Event("X", system=True))):
    it3 = SyncInterpreter(create_machine(STAR, logic=MachineLogic())); it3.start()
    it3.send(e)
    print(f"C sync '*' {lbl}: {set(it3.current_state_ids)}")
    it3.stop()

# sync onUnhandled
UNH = {"id": "u", "initial": "a", "onUnhandled": "error", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
for lbl, e in (("plain ", Event("NOPE")), ("forged", Event("NOPE", system=True))):
    it4 = SyncInterpreter(create_machine(UNH, logic=MachineLogic())); it4.start()
    try:
        it4.send(e); print(f"D sync onUnhandled {lbl}: status={it4.status} err={it4.error!r}")
    except Exception as exc: print(f"D sync onUnhandled {lbl}: {type(exc).__name__}")
    it4.stop()
