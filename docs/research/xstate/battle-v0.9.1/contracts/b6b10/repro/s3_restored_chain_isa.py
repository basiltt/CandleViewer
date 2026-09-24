import asyncio
from xstate_statemachine import Interpreter, create_machine, MachineLogic
from xstate_statemachine.exceptions import RunawayChainError, RestoredError, SnapshotCorruptError
def loop(i,ctx,e,ad): i.send("P")  # self-send storm
CFG={"id":"m","initial":"a","states":{"a":{"on":{"P":{"target":"a","reenter":True,"actions":["loop"]},"GO":"b"}},"b":{}}}
async def main():
    m=create_machine(CFG,logic=MachineLogic(actions={"loop":loop}))
    i=Interpreter(m); await i.start(); await i.send("P"); await asyncio.sleep(0.2)
    print("live trips", i.chain_trips, isinstance(i.last_chain_error, RunawayChainError))
    import json; blob=i.get_persisted_snapshot(); blob=json.dumps(blob) if isinstance(blob,dict) else blob; await i.stop()
    j=Interpreter.from_snapshot(blob, m); await j.start()
    e=j.last_chain_error
    print("restored trips", j.chain_trips, type(e).__name__, isinstance(e,RunawayChainError), isinstance(e,RestoredError))
    await j.stop()
asyncio.run(main())
