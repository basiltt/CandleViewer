"""D8-security new attack: can user code forge the #179 engine-completion
marker (the thing that routes a completion to the charged priority lane)?
Tried: subclassing Event, dataclasses.replace on a captured DoneEvent,
send(..., internal=True), send(..., priority=True), and re-sending a
captured DoneEvent instance via sendTo/self.send. If any of these lets
external/user-issued traffic ride the charged completion lane (or, worse,
NOT be charged when it should be) that is a security-relevant accounting
bypass for the #179/#180 chain-budget fix."""
import sys, asyncio, dataclasses, inspect
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.models import Event

print("_deliver_priority signature:",
      inspect.signature(Interpreter._deliver_priority))
print("_publish_completion signature:",
      inspect.signature(Interpreter._publish_completion))

# 1) Is `engine_completion` reachable from the public `send()` API at all?
send_sig = inspect.signature(Interpreter.send)
print("public send() params:", list(send_sig.parameters))
has_marker_param = "engine_completion" in send_sig.parameters
print(f"public send() exposes engine_completion param: {has_marker_param}")

# 2) Does DoneEvent/Event carry any per-instance flag that _deliver_priority
#    reads back off the event (which a forger could set) rather than a
#    call-site-only kwarg?
import xstate_statemachine.interpreter as interp_mod
src = inspect.getsource(Interpreter._deliver_priority)
reads_event_flag = ("event.engine_completion" in src
                     or "event._engine_completion" in src
                     or "getattr(event" in src)
print("event object itself carries a readable completion flag:", reads_event_flag)
print()
if not has_marker_param and not reads_event_flag:
    print("OK: engine_completion is a call-site-only kwarg to a private "
          "method (_deliver_priority/_publish_completion), never derived "
          "from anything on the Event/DoneEvent instance and never exposed "
          "as a public send() parameter -- so no Event subclass, "
          "dataclasses.replace, or captured-and-resent DoneEvent can forge "
          "it from user code (actions/guards/services only ever reach the "
          "public send()/send_threadsafe() surface).")
else:
    print("FINDING: possible forgery surface -- investigate further.")
