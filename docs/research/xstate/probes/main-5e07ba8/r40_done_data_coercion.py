"""get_snapshot() uses json.dumps(default=str): a DoneEvent payload with a
non-JSON value is SILENTLY stringified. On restore the onDone handler receives
a str where it expects a Decimal/datetime -- no error, no warning."""
import sys, asyncio, json, decimal
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.events import DoneEvent
seen={}
def cap(i,c,e,a): seen["data"]=e.data
CFG={"id":"m","initial":"a","states":{"a":{"on":{"done.invoke.svc":{"target":"b","actions":["cap"]}}},"b":{}}}
async def main():
    i=Interpreter(create_machine(CFG, logic=MachineLogic(actions={"cap":cap}))); await i.start()
    i._event_queue.put_nowait(DoneEvent(type="done.invoke.svc", data={"amount":decimal.Decimal("10.50")}, src="svc"))
    s=i.get_snapshot(); await i.stop()
    print("persisted:", json.loads(s)["pending_events"])
    i2=Interpreter.from_snapshot(s, create_machine(CFG, logic=MachineLogic(actions={"cap":cap})))
    await i2.start(); await asyncio.sleep(0.3)
    d=seen.get("data")
    print("onDone received:", d, "types:", {k:type(v).__name__ for k,v in d.items()})
    print("VERDICT: Decimal -> str, silently:", isinstance(d["amount"], str))
    await i2.stop()
asyncio.run(main())
