"""K-4b: foreign thread using internal=True — charged to maxIterations?
And: an action's own worker thread using default (internal=None)."""
import asyncio, threading
from xstate_statemachine import Interpreter, MachineLogic, create_machine
CFG={"id":"t","initial":"a","maxIterations":20,
     "states":{"a":{"on":{"PING":{"target":"a","actions":["n"]}}}}}
async def run(label, internal):
    hits={"n":0}
    def n(i,c,e,a):
        hits["n"]+=1
        if hits["n"]<300:
            t=threading.Thread(target=lambda: i.send_threadsafe("PING", internal=internal))
            t.start()
    m=create_machine(CFG, logic=MachineLogic(actions={"n":n}))
    i=Interpreter(m); await i.start(); await i.send("PING")
    await asyncio.sleep(1.5)
    print(f"{label}: hits={hits['n']} status={i.status} "
          f"err={type(i.error).__name__ if i.error else None}")
    await i.stop()
async def main():
    await run("plain Thread internal=None (doc says NOT charged)", None)
    await run("plain Thread internal=True (doc: charged)", True)
asyncio.run(main())
