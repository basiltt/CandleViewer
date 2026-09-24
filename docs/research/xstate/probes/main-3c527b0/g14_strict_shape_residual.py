"""G-14: strict mode still exempts by NAME via ENGINE_EVENT_SHAPES.
#79's premise is provenance, but `is_known_event` (models.py:1560) is still
a name test, so a user event whose name merely MATCHES an engine shape
passes strict undeclared -- the exact class of bug #79 set out to close,
narrowed but not closed."""
from xstate_statemachine import Event, MachineLogic, create_machine
from xstate_statemachine.sync_interpreter import SyncInterpreter

CFG = {"id": "s", "initial": "a", "states": {"a": {"on": {"GO": "a"}}}}

for name in ["done.typo", "done.review", "error.validation",
             "done.invoke.NEVER_INVOKED", "done.state.NO_SUCH_STATE",
             "error.platform.NOT_A_SERVICE", "after.party",
             "after.9999999", "xstate.whatever", "xstate.done.actor.ghost",
             "___xstate_forged"]:
    it = SyncInterpreter(create_machine(CFG, logic=MachineLogic()), strict=True)
    it.start()
    try:
        it.send(Event(name))
        print(f"  {name:32s} ACCEPTED   <-- undeclared, strict did not fire")
    except Exception as e:
        print(f"  {name:32s} {type(e).__name__}")
    it.stop()
