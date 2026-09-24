"""D-semantics repro: an invoked CHILD MACHINE's `output` does not reach
the parent's done.invoke.<id> payload."""
import asyncio, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, create_machine

seen = {}
def grab(i, c, e, a):
    seen["type"] = e.type
    seen["data"] = getattr(e, "data", "<no .data>")

child = create_machine({"id":"child","initial":"w","output":{"code":7},
    "states":{"w":{"always":"fin"},"fin":{"type":"final"}}}, logic=MachineLogic())

CFG={"id":"m","initial":"run","states":{
  "run":{"invoke":{"id":"kid","src":"childMachine",
         "onDone":{"target":"ok","actions":["grab"]}}},
  "ok":{}}}

async def main():
    # First: confirm the child machine standalone resolves its output.
    ci = await Interpreter(create_machine(
        {"id":"child","initial":"w","output":{"code":7},
         "states":{"w":{"always":"fin"},"fin":{"type":"final"}}},
        logic=MachineLogic())).start()
    await asyncio.sleep(0.1)
    print("child standalone status/output:", ci.status, ci.output)

    i = await Interpreter(create_machine(CFG, logic=MachineLogic(
        services={"childMachine": child}, actions={"grab": grab}))).start()
    await asyncio.sleep(0.3)
    print("parent state :", sorted(i.current_state_ids))
    print("done event   :", seen)
    print("VERDICT      :", "DEFECT - child output lost"
          if seen.get("data") != {"code": 7} else "ok")
    await i.stop()
asyncio.run(main())
