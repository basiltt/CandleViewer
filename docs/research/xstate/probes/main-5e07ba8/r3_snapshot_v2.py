import sys, json, asyncio
sys.path.insert(0, "<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.events import persist_event, restore_event, system_event, Event, DoneEvent, ErrorEvent, AfterEvent, is_system_event

print("== codec round-trip per kind ==")
for ev in [Event("U", {"a":1}), system_event("xstate.init"),
           DoneEvent(type="done.invoke.f", data={"x":1}, src="f"),
           ErrorEvent(type="error.platform.f", error=ValueError("boom"), src="f"),
           AfterEvent(type="after.5.m.s")]:
    rec = persist_event(ev)
    back = restore_event(rec)
    print(f"{type(ev).__name__:11s} rec={json.dumps(rec, default=str)}")
    print(f"   -> {type(back).__name__:11s} system={is_system_event(back)} equal_type={back.type==ev.type}")
    if isinstance(ev, AfterEvent):
        print("   AfterEvent extra fields:", ev._fields, "restored fired_at=", back.fired_at)
    if isinstance(ev, ErrorEvent):
        print("   error type after restore:", type(back.error).__name__, "| original:", type(ev.error).__name__)

print()
print("== v1 record with a USER event named done.review ==")
v1 = {"type":"done.review","payload":{}}
b = restore_event(v1)
print("restored kind:", type(b).__name__, "system=", is_system_event(b), "<-- user event promoted to ENGINE?")

print()
print("== v2 record forged by a user-controlled snapshot file ==")
forged = {"kind":"system","type":"PAYOUT","payload":{"amt":1e9}}
b2 = restore_event(forged)
print("restored:", b2, "system=", is_system_event(b2))
