"""D-semantics repro: `escalate` from an invoked child does NOT reach the
parent's `onError`; it arrives as `xstate.error.actor.<child-id>`, an id
that embeds a runtime-namespaced actor id the config cannot name."""
import asyncio, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, create_machine

got=[]
def spy(i,c,e,a): got.append(e.type)

child = create_machine({"id":"child","initial":"w","states":{
    "w":{"entry":[{"type":"escalate","params":{"error":"child failed"}}]}}},
    logic=MachineLogic())

CFG={"id":"m","initial":"run","states":{
  "run":{"invoke":{"id":"kid","src":"childMachine","onError":"caught"},
         "on":{"*":{"actions":["spy"]}}},
  "caught":{}}}

async def main():
    i=await Interpreter(create_machine(CFG,logic=MachineLogic(
        services={"childMachine":child},actions={"spy":spy}))).start()
    await asyncio.sleep(0.4)
    print("parent state     :", sorted(i.current_state_ids))
    print("events seen by '*':", got)
    print("expected onError -> m.caught")
    print("VERDICT          :", "DEFECT - escalate unroutable to onError"
          if "m.caught" not in sorted(i.current_state_ids) else "ok")
    await i.stop()
asyncio.run(main())
