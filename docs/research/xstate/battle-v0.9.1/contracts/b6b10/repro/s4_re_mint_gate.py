import asyncio, gc
from xstate_statemachine import Interpreter, create_machine
from xstate_statemachine.plugins import PluginBase
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.events import re_mint
class H(PluginBase):
    n=0
    def on_receipt_dropped(s,i,t): H.n+=1
async def main():
    i=Interpreter(create_machine({"id":"m","initial":"a","states":{"a":{"on":{"X":"a"}}}}),clock=SimulatedClock()); i.use(H()); await i.start()
    i.send("X", wait=True)  # dropped on the floor deliberately
    for _ in range(10): await asyncio.sleep(0)
    gc.collect(); await asyncio.sleep(0)
    print("dropped_receipts", i.dropped_receipts, "hook", H.n)
    try: re_mint({"type":"X"}); print("re_mint accepted user event: BAD")
    except Exception as e: print("re_mint refuses user event:", type(e).__name__)
    await i.stop()
asyncio.run(main())
