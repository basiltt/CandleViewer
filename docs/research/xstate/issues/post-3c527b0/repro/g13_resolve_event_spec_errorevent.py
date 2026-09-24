"""G-13: `_resolve_event_spec` normalises a non-Event into
`Event(type=..., payload=getattr(resolved,'data',{}) or {})`.
For an `ErrorEvent`, `.data` is the DEPRECATED property returning the
EXCEPTION, so re-sending an ErrorEvent through `sendTo`/`raise` yields an
Event whose `payload` is an exception object, not a dict -- AND trips the
DeprecationWarning from inside the engine."""
import asyncio, warnings
from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.events import ErrorEvent, DoneEvent
from xstate_statemachine.interpreter import Interpreter

async def main():
    it = await Interpreter(create_machine(
        {"id": "m", "initial": "a", "states": {"a": {}}}, logic=MachineLogic())).start()
    ee = ErrorEvent(type="error.platform.svc", error=ValueError("boom"), src="svc")
    de = DoneEvent(type="done.invoke.svc", data={"k": 1}, src="svc")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        r1 = it._resolve_event_spec(ee, ee)
        r2 = it._resolve_event_spec(de, de)
        deps = [x for x in w if issubclass(x.category, DeprecationWarning)]
    print("DoneEvent  ->", repr(r1 := r2), "payload type:", type(r2.payload).__name__)
    print("ErrorEvent ->", repr(it._resolve_event_spec(ee, ee)))
    out = it._resolve_event_spec(ee, ee)
    print("  payload:", repr(out.payload), " type:", type(out.payload).__name__,
          " <-- expected dict")
    print("  isinstance(payload, dict):", isinstance(out.payload, dict))
    print("  DeprecationWarnings from engine call:", len(deps),
          [f"{x.filename.split(chr(92))[-1]}:{x.lineno}" for x in deps])
    print("  event.payload.get(...) would now raise:", end=" ")
    try:
        out.payload.get("x"); print("no")
    except AttributeError as e: print("AttributeError:", e)
    await it.stop()

asyncio.run(main())
