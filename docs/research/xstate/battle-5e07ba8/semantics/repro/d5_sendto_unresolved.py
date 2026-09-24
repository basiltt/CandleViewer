"""D-semantics repro: `sendTo` with an unresolvable target drops the event
silently -- no error, no receipt failure, no plugin hook."""
import asyncio, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG={"id":"m","initial":"s","states":{
  "s":{"on":{"GO":{"actions":[{"type":"sendTo","params":{
        "to":"no_such_actor","event":{"type":"PING"}}}]}}}}}

async def main():
    i = await Interpreter(create_machine(CFG, logic=MachineLogic())).start()
    r = await i.send("GO", wait=True)
    await asyncio.sleep(0.1)
    print("receipt        :", r)
    print("last_transition_ok:", i.last_transition_ok)
    print("last_error     :", getattr(i,"last_error",None))
    print("status         :", i.status)
    print("VERDICT        :", "silent drop" if (r.error is None
          and i.last_transition_ok and getattr(i,'last_error',None) is None)
          else "observable")
    await i.stop()
asyncio.run(main())
