import asyncio, logging; logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, Interpreter, Event
cfg={"id":"m","initial":"a","states":{"a":{"on":{"T":{"target":"a"}}}}}
async def main():
    i=await Interpreter(create_machine(cfg)).start()
    ev=Event(type="T")
    r1,r2=await asyncio.gather(i.send(ev,wait=True), i.send(ev,wait=True))
    print("both receipts:", r1.delivered if hasattr(r1,'delivered') else r1, r2)
    await i.stop()
asyncio.run(asyncio.wait_for(main(),5))
