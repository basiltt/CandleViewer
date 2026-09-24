"""R13-01 refutation probe: LIVE (no snapshot) priority lane vs drain_pending.
A slow action holds the run loop; send() and send_priority() both land in
queues. pending_events shows 4; drain_pending returns only the inbox."""
import asyncio
from xstate_statemachine import create_machine, MachineLogic, Interpreter

CFG = {"id": "m", "initial": "a", "states": {
    "a": {"on": {"GO": {"target": "b", "actions": ["slow"]},
                 "P1": "a", "P2": "a", "I1": "a", "I2": "a"}},
    "b": {"on": {"P1": "b", "P2": "b", "I1": "b", "I2": "b"}}}}

async def slow(i, c, e, a):
    await asyncio.sleep(1.0)

async def main():
    m = create_machine(CFG, logic=MachineLogic(actions={"slow": slow}))
    i = Interpreter(m)
    await i.start()
    await i.send("GO")
    await asyncio.sleep(0.2)          # run loop parked inside `slow`
    await i.send("I1", wait=False)
    i.send_priority("P1", wait=False)
    await i.send("I2", wait=False)
    i.send_priority("P2", wait=False)
    await asyncio.sleep(0.05)
    view = [getattr(e, "type", e) for e in i.pending_events]
    drained = [getattr(e, "type", e) for e in await i.drain_pending()]
    print("live pending_events :", view)
    print("live drain_pending  :", drained)
    print("LOST                :", [t for t in view if t not in drained])
    print("still queued after  :", [getattr(e,'type',e) for e in i.pending_events])
    await i.stop()

asyncio.run(asyncio.wait_for(main(), 25))
