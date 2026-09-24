import asyncio, json, sys
from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from order_machine import build

async def main():
    m = build()
    clock = SimulatedClock()
    i = await Interpreter(m, clock=clock).start()
    print("start", sorted(i.current_state_ids))
    await i.send("SUBMIT", qty=7)
    await asyncio.sleep(0.05)
    print("after submit", sorted(i.current_state_ids), i.context["trace"])
    await i.send("RISK_OK"); await i.send("FILL", n=2)
    await asyncio.sleep(0.05)
    print("now", sorted(i.current_state_ids), i.context)
    snap = i.get_snapshot()
    print("snapshot keys", sorted(json.loads(snap).keys()))
    print("version", json.loads(snap)["version"])
    await i.stop()

asyncio.run(main())
