import sys, inspect, asyncio, logging
sys.path.insert(0, r"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, Interpreter, SyncInterpreter, MachineLogic
from xstate_statemachine.base_interpreter import BaseInterpreter
from xstate_statemachine.plugins import PluginBase

print("=== D-persistence-1: from_snapshot has no clock= ===")
print("  sig:", inspect.signature(BaseInterpreter.from_snapshot))
print("  'clock' in params:", 'clock' in inspect.signature(BaseInterpreter.from_snapshot).parameters)

print("\n=== D-concurrency-5: async plugin hooks never awaited ===")
calls=[]
class AsyncHook(PluginBase):
    async def on_event_received(self, interp, ev): calls.append(ev.type)
async def main():
    m=create_machine({"id":"z","initial":"a","states":{"a":{"on":{"GO":"b"}},"b":{}}},logic=MachineLogic())
    it=Interpreter(m); it.use(AsyncHook()); await it.start()
    await it.send("GO"); await asyncio.sleep(0.05); await it.stop()
    print(f"  async hook body executed: {len(calls)} (expected 1 if awaited)")
asyncio.run(main())

print("\n=== D-fuzz-5 / D-semantics: send(non-event) raises bare TypeError ===")
m=create_machine({"id":"t","initial":"a","states":{"a":{}}},logic=MachineLogic())
i=SyncInterpreter(m); i.start()
from xstate_statemachine.exceptions import XStateMachineError
for bad in [42, None, [1], object()]:
    try: i.send(bad); print(f"  {bad!r}: ACCEPTED")
    except XStateMachineError as e: print(f"  {bad!r}: XStateMachineError (catchable)")
    except Exception as e: print(f"  {type(bad).__name__}: {type(e).__name__} <- NOT an XStateMachineError")
