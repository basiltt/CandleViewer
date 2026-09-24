"""K-13: consequence of a leaked _threadsafe_self_sends_in_flight.

If the counter can be incremented and its `_deliver` never run (loop
refuses the event / machine stopped mid-flight), the chain budget never
resets, so a long-lived machine eventually trips RunawayChainError on
ordinary unrelated traffic.
"""
import asyncio
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import RunawayChainError

CFG={"id":"c","initial":"a","maxIterations":25,
     "states":{"a":{"on":{"X":{"target":"a","actions":["tick"]}}}}}

async def main():
    n={"i":0}
    def tick(i,c,e,a): n["i"]+=1
    m=create_machine(CFG, logic=MachineLogic(actions={"tick":tick}))
    i=Interpreter(m); await i.start()
    # simulate the leak directly (reachable when _deliver is dropped)
    i._threadsafe_self_sends_in_flight = 1
    for k in range(60):
        await i.send("X")
    await asyncio.sleep(0.4)
    print(f"leaked counter=1, 60 external sends -> status={i.status} "
          f"err={type(i.error).__name__ if i.error else None} "
          f"raise_depth={i._raise_depth} ticks={n['i']}")
    await i.stop()

asyncio.run(main())
