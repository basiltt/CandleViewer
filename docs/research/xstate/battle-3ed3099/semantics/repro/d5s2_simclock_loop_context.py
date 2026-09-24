"""D5-semantics-2 repro: SimulatedClock.increment() picks sync-vs-async by the
AMBIENT EVENT LOOP, not by the engine it is driving. A `SyncInterpreter` driven
from inside any running loop (a pytest-asyncio test, an async harness, an async
main) silently does not advance: increment() returns a _MustAwait that the
sync-style call site never awaits. The only signal is a GC-time
warnings.warn -- invisible under `logging.disable` / `-W ignore` / a warning
filter, and it arrives long after the assertion has already passed.
"""
import asyncio, logging, warnings
logging.disable(logging.CRITICAL)
from xstate_statemachine import (MachineLogic, SimulatedClock, SyncInterpreter,
                                 create_machine)

CFG = {"id": "L", "initial": "s1",
       "states": {"s1": {"after": {100: "s2"}},
                  "s2": {"after": {100: "s3"}},
                  "s3": {"type": "final"}}}
mk = lambda: create_machine(CFG, logic=MachineLogic())

def ladder(label):
    c = SimulatedClock()
    s = SyncInterpreter(mk(), clock=c).start()
    seq = [sorted(s.current_state_ids)]
    rets = []
    for _ in range(2):
        rets.append(type(c.increment(100)).__name__)
        seq.append(sorted(s.current_state_ids))
    s.stop()
    print(f"  {label:26} increment()->{rets}  states={seq}")

print("SyncInterpreter + SimulatedClock, NO running loop:")
ladder("outside loop")
print("SyncInterpreter + SimulatedClock, INSIDE a running loop:")
async def m():
    ladder("inside loop")
asyncio.run(m())
print("\n>>> Same engine, same clock, same calls: inside a loop the ladder")
print(">>> never advances. Identical code, different ambient context.")
print("\nIs anything raised or logged at the call site? ", end="")
async def m2():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        c = SimulatedClock()
        s = SyncInterpreter(mk(), clock=c).start()
        c.increment(100)
        print(f"warnings at call site = {len(w)} (GC-time only)")
        s.stop()
asyncio.run(m2())
